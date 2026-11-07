#include "StreetballWorld.h"
#include "StreetballGym.h"
#include "StreetballAnimInstance.h"
#include "StreetballTracker.h"
#include "StreetballHUDWidget.h"
#include "BroadcastCamera.h"
#include "MuJoCoSim.h"
#include "SimClock.h"
#include "MuJoCoBoneMapper.h"
#include "PolicyRunner.h"
#include "Misc/CommandLine.h"
#include "Blueprint/UserWidget.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/Paths.h"
#include "UObject/ConstructorHelpers.h"

// ---------------------------------------------------------------------------- character
AStreetballCharacter::AStreetballCharacter()
{
	PrimaryActorTick.bCanEverTick = false;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Mesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Mesh"));
	Mesh->SetupAttachment(Root);
	// Manny faces +Y in mesh space; -90 deg yaw makes it face actor +X, which is sim +X.
	Mesh->SetRelativeRotation(FRotator(0.f, -90.f, 0.f));
	Mesh->SetSimulatePhysics(false);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetEnableGravity(false);
	Mesh->SetAnimationMode(EAnimationMode::AnimationBlueprint);
	Mesh->SetAnimInstanceClass(UStreetballAnimInstance::StaticClass());
	Mesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	Mesh->bEnableUpdateRateOptimizations = false;
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> Manny(TEXT("/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple"));
	if (Manny.Succeeded()) Mesh->SetSkeletalMeshAsset(Manny.Object);
}

// ---------------------------------------------------------------------------- geom actor
AStreetballGeomActor::AStreetballGeomActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	SetRootComponent(Mesh);
	Mesh->SetSimulatePhysics(false);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetEnableGravity(false);
	Mesh->SetMobility(EComponentMobility::Movable);
}

// ---------------------------------------------------------------------------- world
AStreetballWorld::AStreetballWorld()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
}

void AStreetballWorld::BeginPlay()
{
	Super::BeginPlay();
	if (!Setup(GetWorld())) return;
	// Presentation hooks need a local player; automation worlds have none.
	if (APlayerController* PC = UGameplayStatics::GetPlayerController(GetWorld(), 0))
	{
		if (Camera) PC->SetViewTarget(Camera);
		HUD = CreateWidget<UStreetballHUDWidget>(PC, UStreetballHUDWidget::StaticClass());
		if (HUD) HUD->AddToViewport(10);
	}
}

bool AStreetballWorld::EnginePrimitiveForGeom(int32 GeomType, const FVector& SizeM, FString& OutMeshPath, FVector& OutScale)
{
	switch (GeomType)
	{
	case mjGEOM_PLANE:
		OutMeshPath = TEXT("/Engine/BasicShapes/Plane.Plane");
		OutScale = FVector(SizeM.X > 0 ? SizeM.X * 2.0 : 100.0, SizeM.Y > 0 ? SizeM.Y * 2.0 : 100.0, 1.0);
		return true;
	case mjGEOM_SPHERE:
		OutMeshPath = TEXT("/Engine/BasicShapes/Sphere.Sphere");
		OutScale = FVector(SizeM.X * 2.0);
		return true;
	case mjGEOM_CAPSULE:
	case mjGEOM_CYLINDER:
		OutMeshPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
		OutScale = FVector(SizeM.X * 2.0, SizeM.X * 2.0, SizeM.Y * 2.0 + (GeomType == mjGEOM_CAPSULE ? SizeM.X * 2.0 : 0.0));
		return true;
	case mjGEOM_BOX:
		OutMeshPath = TEXT("/Engine/BasicShapes/Cube.Cube");
		OutScale = FVector(SizeM.X * 2.0, SizeM.Y * 2.0, SizeM.Z * 2.0);
		return true;
	default:
		return false;
	}
}

UPolicyRunner* AStreetballWorld::LoadPolicy(const FString& Family)
{
	// File from the transition table ("policies/<family>.onnx"), else <PolicyDir>/<family>.onnx.
	FString Rel = Director ? Director->PolicyFileFor(Family) : FString();
	if (Rel.IsEmpty()) Rel = FPaths::Combine(PolicyDir, Family + TEXT(".onnx"));
	const FString Path = FPaths::IsRelative(Rel) ? FPaths::Combine(Streetball::SimDir(), Rel) : Rel;
	if (FPaths::FileExists(Path))
	{
		UPolicyRunner* R = NewObject<UPolicyRunner>(this, *FString::Printf(TEXT("Policy_%s"), *Family));
		if (R->LoadOnnx(Path, FObsBuilder::NumObs, FObsBuilder::NumAction))
		{
			RealPolicies.Add(Family);
			UE_LOG(LogStreetball, Log, TEXT("Policy %s: trained model %s"), *Family, *Path);
			return R;
		}
		UE_LOG(LogStreetball, Warning, TEXT("Policy %s: %s failed to load, using fallback"), *Family, *Path);
	}
	return Fallback;
}

bool AStreetballWorld::Setup(UWorld* InWorld)
{
	if (!InWorld) return false;

	// ---- sim --------------------------------------------------------------
	Sim = NewObject<UMuJoCoSim>(this, TEXT("Sim"));
	if (!Sim->LoadXml(Streetball::SceneXmlPath()))
	{
		UE_LOG(LogStreetball, Error, TEXT("World: failed to load %s"), *Streetball::SceneXmlPath());
		return false;
	}
	PelvisBody = Sim->BodyId(TEXT("pelvis"));
	BallBody = Sim->BodyId(TEXT("ball"));

	// ---- pre-allocated actors ----------------------------------------------
	FActorSpawnParameters SP;
	SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Character = InWorld->SpawnActor<AStreetballCharacter>(AStreetballCharacter::StaticClass(), FTransform::Identity, SP);
	Camera = InWorld->SpawnActor<ABroadcastCamera>(ABroadcastCamera::StaticClass(), FTransform(FVector(0, 930, 220)), SP);

	GeomActors.Reset();
	const int32 NG = Sim->NumGeoms();
	for (int32 g = 0; g < NG; ++g)
	{
		const int32 Body = Sim->GetGeomBody(g);
		const bool bHumanoid = Body > 0 && Sim->IsBodyDynamic(Body) && Body != BallBody;
		if (bHumanoid && !bShowHumanoidGeoms) continue;
		FString MeshPath; FVector Scale;
		if (!EnginePrimitiveForGeom(Sim->GetGeomType(g), Sim->GetGeomSize(g), MeshPath, Scale)) continue;
		UStaticMesh* SM = LoadObject<UStaticMesh>(nullptr, *MeshPath);
		if (!SM) continue;
		AStreetballGeomActor* A = InWorld->SpawnActor<AStreetballGeomActor>(AStreetballGeomActor::StaticClass(), FTransform::Identity, SP);
		A->GeomId = g;
		A->BodyId = Body;
		A->bDynamic = Sim->IsBodyDynamic(Body);
		A->MeshScale = Scale;
		A->Mesh->SetStaticMesh(SM);
		const FLinearColor C = Sim->GetGeomColor(g);
		if (UMaterialInterface* Base = A->Mesh->GetMaterial(0))
		{
			if (UMaterialInstanceDynamic* MID = UMaterialInstanceDynamic::Create(Base, A))
			{
				MID->SetVectorParameterValue(TEXT("Color"), C);
				A->Mesh->SetMaterial(0, MID);
			}
		}
		const FTransform GX = Sim->GetGeomTransformUE(g);
		A->SetActorTransform(FTransform(GX.GetRotation(), GX.GetLocation(), Scale));
		if (A->bDynamic) A->GeomInBody = GX.GetRelativeTransform(Sim->GetBodyTransformUE(Body));
		else A->Mesh->SetMobility(EComponentMobility::Static);
		GeomActors.Add(A);
		if (Body == BallBody) BallActor = A;
	}

	// ---- clock, mapper, tracker, director ---------------------------------
	Clock = NewObject<USimClock>(this, TEXT("Clock"));
	BoneMapper = NewObject<UMuJoCoBoneMapper>(this, TEXT("BoneMapper"));
	BoneMapper->Initialize(Character->Mesh, Sim, Streetball::HumanoidSpecPath());
	Tracker = NewObject<UStreetballTracker>(this, TEXT("Tracker"));
	Director = NewObject<UStreetballDirector>(this, TEXT("Director"));

	Sim->ResetToKeyframe(KeyframeName);
	const int32 Key = Sim->KeyId(KeyframeName);
	HoldCtrl.SetNum(Sim->NumActuators());
	for (int32 i = 0; i < HoldCtrl.Num(); ++i) HoldCtrl[i] = Key >= 0 ? (float)Sim->GetModel()->key_ctrl[Key * Sim->NumActuators() + i] : 0.f;
	Sim->SetCtrl(HoldCtrl);
	Tracker->Initialize(Sim);
	{
		FString TP = TransitionTablePath;
		if (FPaths::IsRelative(TP)) TP = FPaths::Combine(Streetball::SimDir(), TP);
		Director->LoadTransitionTable(TP);          // falls back to the built-in v1 table
	}
	Director->Initialize(DirectorSeed);
	{
		int32 MaxTier = 5;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballMaxTier="), MaxTier)) Director->MaxTier = FMath::Clamp(MaxTier, 1, 5);
		if (Director->MaxTier < 5) UE_LOG(LogStreetball, Log, TEXT("Director: tiers capped at %d"), Director->MaxTier);
	}

	// ---- policies: one per state, trained file if present else the dummy ----
	ObsBuilder.Initialize(Sim, Streetball::ObsSpecPath());
	{
		FString FB = FallbackPolicy;
		if (FPaths::IsRelative(FB)) FB = FPaths::Combine(Streetball::SimDir(), FB);
		Fallback = NewObject<UPolicyRunner>(this, TEXT("Policy_fallback"));
		if (!Fallback->LoadOnnx(FB, FObsBuilder::NumObs, FObsBuilder::NumAction))
		{
			UE_LOG(LogStreetball, Warning, TEXT("No fallback policy at %s; states without a trained policy hold the keyframe"), *FB);
			Fallback = nullptr;
		}
	}
	RealPolicies.Reset();
	Policies.Reset();
	for (const TPair<FString, FString>& Fam : Director->GetPolicyFiles())   // one runner per family, all preloaded
	{
		Policies.Add(Fam.Key, LoadPolicy(Fam.Key));
	}
	PrevAction.SetNumZeroed(FObsBuilder::NumJoints);

	// ---- audio --------------------------------------------------------------
	AudioBank = AudioBankPath.IsEmpty() ? nullptr : LoadObject<UCourtAudioBank>(nullptr, *AudioBankPath);
	if (!AudioBank) UE_LOG(LogStreetball, Warning, TEXT("Audio bank %s not found: events are tracked but silent"), *AudioBankPath);
	AudioProc.Initialize(Sim);
	if (AudioBank) { AudioProc.SpeedForFullVolume = AudioBank->SpeedForFullVolume; AudioProc.MinVolume = AudioBank->MinVolume; AudioProc.PitchRange = AudioBank->PitchRange; }
	AudioPlayer.Initialize(this, AudioBank, 8);

	Clock->Initialize(Sim, 10);
	Clock->OnControlStep.BindUObject(this, &AStreetballWorld::OnControlStep);
	Clock->OnPhysicsStep.BindUObject(this, &AStreetballWorld::OnPhysicsStep);
	{
		// first episode starts like every later one: tiers 1-2 keep the ball away from the feet
		FStreetballResetSpec Start; Start.Reason = TEXT("startup");
		UStreetballDirector::ParkBallForTier(Director->GetProgress().ActiveTier, Start);
		if (Start.bPlaceBall) ApplyReset(Start);
	}
	bReady = true;
	UpdateVisuals();
	UE_LOG(LogStreetball, Log, TEXT("World ready: %d geom actors, %d trained policies (%s), fallback %s"),
		GeomActors.Num(), RealPolicies.Num(), *FString::Join(RealPolicies, TEXT(",")), Fallback ? TEXT("loaded") : TEXT("none"));
	return true;
}

void AStreetballWorld::ApplyReset(const FStreetballResetSpec& Spec)
{
	++ResetCount;
	Sim->ResetToKeyframe(KeyframeName);
	const mjModel* M = Sim->GetModel();
	TArray<double> Q(Sim->QPos());
	if (Spec.bOffsetRoot)
	{
		const int32 R = M->jnt_qposadr[Sim->JointId(TEXT("root"))];
		Q[R] = Spec.RootXY.X; Q[R + 1] = Spec.RootXY.Y;
		Q[R + 3] = FMath::Cos(Spec.RootYaw / 2); Q[R + 4] = 0; Q[R + 5] = 0; Q[R + 6] = FMath::Sin(Spec.RootYaw / 2);
	}
	if (Spec.bPlaceBall)
	{
		const int32 B = M->jnt_qposadr[Sim->JointId(TEXT("ball"))];
		Q[B] = Spec.BallPos.X; Q[B + 1] = Spec.BallPos.Y; Q[B + 2] = Spec.BallPos.Z;
		Q[B + 3] = 1; Q[B + 4] = Q[B + 5] = Q[B + 6] = 0;
	}
	Sim->SetQPos(Q);
	TArray<double> V; V.SetNumZeroed(Sim->NumV());
	Sim->SetQVel(V);
	Sim->SetCtrl(HoldCtrl);
	Sim->Forward();
	Tracker->ResetState();
	Director->NotifyResetApplied(Tracker->State());
	if (Director->GetProgress().ActiveTier >= 3) Tracker->GrantControl();   // ball starts at the hand
	for (float& A : PrevAction) A = 0.f;
	if (Clock) Clock->Resnapshot();
	UE_LOG(LogStreetball, Log, TEXT("Reset #%d applied (%s)"), ResetCount, *Spec.Reason);
}

void AStreetballWorld::OnControlStep(UMuJoCoSim* InSim)
{
	const double Dt = Clock ? Clock->GetTimestep() * Clock->GetSubstepsPerControl() : 0.02;
	const FTrackedState& S = Tracker->Update(Dt);
	Director->Update(S, Dt, DirOut);
	if (DirOut.bScoreEvent)
	{
		FCourtAudioEvent E = AudioProc.MakeEvent(ECourtSound::NetRattle, S.Time, S.RimPos[0], 4.f, TEXT("score"));
		PendingEvents.Add(E);
	}
	if (DirOut.Reset.bRequested)
	{
		ApplyReset(DirOut.Reset);
		Director->Describe(Tracker->State(), DirOut);
	}
	UPolicyRunner* Policy = nullptr;
	if (TObjectPtr<UPolicyRunner>* Found = Policies.Find(DirOut.PolicyName)) Policy = Found->Get();
	LastPolicyName = DirOut.PolicyName;
	if (Policy && ObsBuilder.IsInitialized())
	{
		// UU_AGENT hand-over rule: PrevAction is passed through unchanged across policy switches.
		const FTrackedState& T = Tracker->State();
		ObsBuilder.Compute(InSim, PrevAction, TConstArrayView<float>(DirOut.Task, 12), T.InControl ? 1.f : 0.f, T.CountdownFrac, Obs);
		if (Policy->Run(Obs, Action))
		{
			TArray<float> Ctrl;
			ObsBuilder.ActionToCtrl(Action, Ctrl);
			InSim->SetCtrl(Ctrl);
			PrevAction = Action;
			return;
		}
	}
	InSim->SetCtrl(HoldCtrl);
}

void AStreetballWorld::OnPhysicsStep(UMuJoCoSim* InSim)
{
	AudioProc.Process(InSim, PendingEvents);
}

void AStreetballWorld::StepControl()
{
	if (!bReady) return;
	OnControlStep(Sim);
	for (int32 i = 0; i < Clock->GetSubstepsPerControl(); ++i) { Sim->Step(1); OnPhysicsStep(Sim); }
}

void AStreetballWorld::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bReady) return;
	Clock->Advance(DeltaSeconds);
	UpdateVisuals();
	UpdateCameraAndHUD(DeltaSeconds);
	for (const FCourtAudioEvent& E : PendingEvents)
	{
		AudioPlayer.Play(E);
		RecentEvents.Add(E);
	}
	if (RecentEvents.Num() > 64) RecentEvents.RemoveAt(0, RecentEvents.Num() - 64, EAllowShrinking::No);
	PendingEvents.Reset();
}

void AStreetballWorld::UpdateCameraAndHUD(float Dt)
{
	const FTrackedState& S = Tracker->State();
	if (Camera)
	{
		FBroadcastInputs In;
		In.Time = S.Time;
		In.Character = S.PelvisPos;
		In.Ball = S.BallPos;
		In.Speed = S.Speed();
		In.State = Director->GetState();
		In.Rim[0] = S.RimPos[0]; In.Rim[1] = S.RimPos[1];
		Camera->UpdateCamera(In, Dt);
	}
	if (HUD) HUD->UpdateFromProgress(Director->GetProgress(), Director->GetState());
}

void AStreetballWorld::UpdateVisuals()
{
	if (!bReady) return;
	const int32 NB = Sim->NumBodies();
	TArray<FVector> P; P.SetNum(NB);
	TArray<FQuat> R; R.SetNum(NB);
	for (int32 b = 0; b < NB; ++b)
	{
		const FTransform X = Clock->GetInterpolatedBody(b);
		P[b] = X.GetLocation();
		R[b] = X.GetRotation();
	}
	if (Character && PelvisBody >= 0)
	{
		Character->SetActorLocation(FVector(P[PelvisBody].X, P[PelvisBody].Y, 0.0));
		BoneMapper->Apply(P, R);
	}
	for (AStreetballGeomActor* A : GeomActors)
	{
		if (!A->bDynamic) continue;
		const FTransform BodyX(R[A->BodyId], P[A->BodyId]);
		const FTransform GX = A->GeomInBody * BodyX;
		A->SetActorTransform(FTransform(GX.GetRotation(), GX.GetLocation(), A->MeshScale));
	}
}
