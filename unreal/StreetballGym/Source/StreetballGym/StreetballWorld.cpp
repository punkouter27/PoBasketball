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
#include "InputCoreTypes.h"
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
#include "GroomComponent.h"
#include "UnrealClient.h"
#include "EngineUtils.h"
#include "GroomAsset.h"
#include "GroomBindingAsset.h"

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

FString AStreetballCharacter::ApplyMainCharacterMesh()
{
	FString Which;
	FParse::Value(FCommandLine::Get(), TEXT("StreetballCharacter="), Which);
	if (!Which.Equals(TEXT("Manny"), ESearchCase::IgnoreCase))
	{
		// Override first (MetaHuman body or any UE5-skeleton mesh), then the cloth grandma, then the plain grandma.
		TArray<FString, TInlineAllocator<3>> Candidates;
		FString Override;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballCharacterMesh="), Override) && !Override.IsEmpty()) Candidates.Add(Override);
		if (!FParse::Param(FCommandLine::Get(), TEXT("StreetballNoCloth"))) Candidates.Add(GrandmaClothMeshPath);
		Candidates.Add(GrandmaMeshPath);
		bool bFound = false;
		for (const FString& Path : Candidates)
		{
			if (USkeletalMesh* SM = LoadObject<USkeletalMesh>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet))
			{
				// Same mannequin bone names and bind joints as Manny, also faces mesh +Y: the -90 deg yaw still applies.
				Mesh->SetSkeletalMeshAsset(SM);
				bFound = true;
				break;
			}
		}
		if (!bFound) UE_LOG(LogStreetball, Log, TEXT("Character: %s not imported yet, using Manny"), GrandmaMeshPath);
	}
	const USkeletalMesh* InUse = Mesh->GetSkeletalMeshAsset();
	const FString Name = InUse ? InUse->GetName() : FString(TEXT("none"));
	UE_LOG(LogStreetball, Log, TEXT("Character mesh: %s (cloth %s)"), *Name, HasCloth() ? TEXT("yes") : TEXT("no"));
	return Name;
}

bool AStreetballCharacter::HasCloth() const
{
	USkeletalMesh* SM = Mesh ? Mesh->GetSkeletalMeshAsset() : nullptr;
	return SM && SM->GetMeshClothingAssets().Num() > 0;
}

int32 AStreetballCharacter::NumGrooms() const
{
	int32 N = 0;
	for (const UGroomComponent* G : Grooms) N += (G && G->GroomAsset) ? 1 : 0;
	return N;
}

void AStreetballCharacter::AttachExtras()
{
	const USkeletalMesh* SM = Mesh->GetSkeletalMeshAsset();
	if (!SM || !SM->GetName().StartsWith(TEXT("SK_Grandma")) || FParse::Param(FCommandLine::Get(), TEXT("StreetballNoGroom"))) return;
	// Strands are authored in the grandma's bind-pose mesh space. With a binding asset they skin with the mesh;
	// without one they ride rigidly on the head bone (offset = inverse of the head's bind transform).
	const FReferenceSkeleton& Ref = SM->GetRefSkeleton();
	FTransform HeadCS = FTransform::Identity;
	for (int32 b = Ref.FindBoneIndex(TEXT("head")); b != INDEX_NONE; b = Ref.GetParentIndex(b)) HeadCS = HeadCS * Ref.GetRefBonePose()[b];
	const TCHAR* Paths[2] = { GroomFlyawaysPath, GroomBrowsPath };
	for (int32 i = 0; i < 2; ++i)
	{
		UGroomAsset* GA = LoadObject<UGroomAsset>(nullptr, Paths[i], nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (!GA) continue;
		const FString BindingPath = FString(Paths[i]).Replace(TEXT("GR_"), TEXT("GB_"));
		UGroomBindingAsset* Binding = LoadObject<UGroomBindingAsset>(nullptr, *BindingPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
		UGroomComponent* G = NewObject<UGroomComponent>(this, *FString::Printf(TEXT("Groom%d"), i));
		G->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		if (Binding)
		{
			G->SetupAttachment(Mesh);
			G->SetGroomAsset(GA, Binding);
		}
		else
		{
			G->SetupAttachment(Mesh, TEXT("head"));
			G->SetRelativeTransform(HeadCS.Inverse());
			G->SetGroomAsset(GA);
		}
		G->RegisterComponent();
		Grooms.Add(G);
		UE_LOG(LogStreetball, Log, TEXT("Character groom: %s (%s)"), *GA->GetName(), Binding ? TEXT("bound to mesh") : TEXT("rigid on head"));
	}
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
	// Substrate court materials (Scripts/make_court_materials.py). Prefix match on the MJCF geom name, longest wins.
	GeomMaterialOverrides.Add(TEXT("floor"), TEXT("/Game/Art/Materials/MI_CourtAsphalt.MI_CourtAsphalt"));
	GeomMaterialOverrides.Add(TEXT("ball"), TEXT("/Game/Art/Materials/MI_Basketball.MI_Basketball"));
	GeomMaterialOverrides.Add(TEXT("rim_bracket"), TEXT("/Game/Art/Materials/MI_SteelPaint.MI_SteelPaint"));
	GeomMaterialOverrides.Add(TEXT("rim_"), TEXT("/Game/Art/Materials/MI_RimPaint.MI_RimPaint"));
	GeomMaterialOverrides.Add(TEXT("board_"), TEXT("/Game/Art/Materials/MI_Backboard.MI_Backboard"));
	GeomMaterialOverrides.Add(TEXT("pole_"), TEXT("/Game/Art/Materials/MI_SteelPaint.MI_SteelPaint"));
	GeomMaterialOverrides.Add(TEXT("arm_"), TEXT("/Game/Art/Materials/MI_SteelPaint.MI_SteelPaint"));
	GeomMaterialOverrides.Add(TEXT("fence_"), TEXT("/Game/Art/Materials/MI_ChainLink.MI_ChainLink"));
}

UMaterialInterface* AStreetballWorld::MaterialOverrideFor(const FString& GeomName) const
{
	UMaterialInterface* Best = nullptr;
	int32 BestLen = -1;
	for (const TPair<FString, TObjectPtr<UMaterialInterface>>& P : LoadedOverrides)
	{
		if (P.Value && P.Key.Len() > BestLen && GeomName.StartsWith(P.Key)) { Best = P.Value; BestLen = P.Key.Len(); }
	}
	return Best;
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
	// Side-by-side comparisons: -StreetballPolicy_<family>=<file> (relative to Content/Sim, e.g. policies/locomotion_amp.onnx)
	FString Override;
	if (FParse::Value(FCommandLine::Get(), *FString::Printf(TEXT("StreetballPolicy_%s="), *Family), Override) && !Override.IsEmpty())
	{
		UE_LOG(LogStreetball, Log, TEXT("Policy %s: command-line override %s"), *Family, *Override);
		Rel = Override;
	}
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

	UMaterialInterface* ShapeMaterial = LoadObject<UMaterialInterface>(nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));

	// Visual-only surroundings (not in the sim, no collision): the high press-box shot looks past the fence, where
	// there was nothing to render and the frame went black. A 400 m apron 2 cm under the court fills it.
	if (!Surroundings)
	{
		if (UStaticMesh* PlaneSM = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Plane.Plane")))
		{
			Surroundings = InWorld->SpawnActor<AStreetballGeomActor>(AStreetballGeomActor::StaticClass(), FTransform::Identity, SP);
			Surroundings->Mesh->SetStaticMesh(PlaneSM);
			if (UMaterialInterface* Base = ShapeMaterial)
			{
				if (UMaterialInstanceDynamic* MID = UMaterialInstanceDynamic::Create(Base, Surroundings))
				{
					MID->SetVectorParameterValue(TEXT("Color"), FLinearColor(0.16f, 0.20f, 0.14f));
					Surroundings->Mesh->SetMaterial(0, MID);
				}
			}
			Surroundings->SetActorTransform(FTransform(FQuat::Identity, FVector(0, 0, -2.0), FVector(400.0, 400.0, 1.0)));
			Surroundings->Mesh->SetMobility(EComponentMobility::Static);
		}
	}

	LoadedOverrides.Reset();
	MaterialOverrideCount = 0;
	if (bPresentation && !FParse::Param(FCommandLine::Get(), TEXT("StreetballNoPresentation")))
	{
		for (const TPair<FString, FString>& P : GeomMaterialOverrides)
		{
			if (UMaterialInterface* MI = LoadObject<UMaterialInterface>(nullptr, *P.Value, nullptr, LOAD_NoWarn | LOAD_Quiet)) LoadedOverrides.Add(P.Key, MI);
		}
	}

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
		// MJCF rgba -> BasicShapeMaterial "Color". The shapes' own slot resolves to DefaultMaterial (no Color
		// parameter), which silently dropped every MJCF colour (orange ball and rims, dark steel, white boards).
		// Textured MJCF materials (the asphalt floor) keep the engine material.
		const bool bMjcfMaterial = Sim->GetModel()->geom_matid[g] >= 0;
		UMaterialInterface* Base = bMjcfMaterial ? A->Mesh->GetMaterial(0) : ShapeMaterial;
		if (UMaterialInterface* Override = bHumanoid ? nullptr : MaterialOverrideFor(Sim->GeomName(g)))
		{
			A->Mesh->SetMaterial(0, Override);
			++MaterialOverrideCount;
		}
		else if (Base && !bMjcfMaterial)
		{
			if (UMaterialInstanceDynamic* MID = UMaterialInstanceDynamic::Create(Base, A))
			{
				MID->SetVectorParameterValue(TEXT("Color"), Sim->GetGeomColor(g));
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
	Character->ApplyMainCharacterMesh();
	BoneMapper->Initialize(Character->Mesh, Sim, Streetball::HumanoidSpecPath());
	if (bPresentation && !FParse::Param(FCommandLine::Get(), TEXT("StreetballNoPresentation"))) Character->AttachExtras();
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
	int32 CliSeed = DirectorSeed;
	if (FParse::Value(FCommandLine::Get(), TEXT("StreetballSeed="), CliSeed))
	{
		DirectorSeed = CliSeed;
	}
	Director->Initialize(DirectorSeed);
	{
		int32 MaxTier = 5;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballMaxTier="), MaxTier)) Director->MaxTier = FMath::Clamp(MaxTier, 1, 5);
		if (Director->MaxTier < 5) UE_LOG(LogStreetball, Log, TEXT("Director: tiers capped at %d"), Director->MaxTier);
		int32 StartTier = 1;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballStartTier="), StartTier) && StartTier > 1)
		{
			Director->StartAtTier(FMath::Min(StartTier, Director->MaxTier));
			UE_LOG(LogStreetball, Log, TEXT("Director: starting at tier %d"), Director->GetProgress().ActiveTier);
		}
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
	PolicyOrder.Reset();
	for (const TPair<FString, FString>& Fam : Director->GetPolicyFiles())   // one runner per family, all preloaded
	{
		const FName FamName(*Fam.Key);
		Policies.Add(FamName, LoadPolicy(Fam.Key));
		PolicyOrder.Add(FamName);
	}
	PrevAction.SetNumZeroed(FObsBuilder::NumJoints);
	Obs.SetNumZeroed(FObsBuilder::NumObs);
	Action.SetNumZeroed(FObsBuilder::NumAction);
	CtrlBuf.SetNumZeroed(Sim->NumActuators());
	QBuf.SetNumZeroed(Sim->NumQ());
	VBuf.SetNumZeroed(Sim->NumV());
	{
		const mjModel* M = Sim->GetModel();
		RootQAdr = M->jnt_qposadr[Sim->JointId(TEXT("root"))];
		BallQAdr = M->jnt_qposadr[Sim->JointId(TEXT("ball"))];
		BallVAdr = M->jnt_dofadr[Sim->JointId(TEXT("ball"))];
	}
	{
		FString HandArg;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballDribbleHand="), HandArg))
		{
			Director->ForcedHand = HandArg.StartsWith(TEXT("l")) ? -1.0 : HandArg.StartsWith(TEXT("r")) ? 1.0 : 0.0;
			UE_LOG(LogStreetball, Log, TEXT("Director: dribble hand forced to %s"), Director->ForcedHand > 0 ? TEXT("right") : Director->ForcedHand < 0 ? TEXT("left") : TEXT("table"));
		}
	}
	PendingEvents.Reserve(64);
	RecentEvents.Reserve(128);

	// ---- audio --------------------------------------------------------------
	AudioBank = AudioBankPath.IsEmpty() ? nullptr : LoadObject<UCourtAudioBank>(nullptr, *AudioBankPath);
	if (!AudioBank) UE_LOG(LogStreetball, Warning, TEXT("Audio bank %s not found: events are tracked but silent"), *AudioBankPath);
	AudioProc.Initialize(Sim);
	if (AudioBank) { AudioProc.SpeedForFullVolume = AudioBank->SpeedForFullVolume; AudioProc.MinVolume = AudioBank->MinVolume; AudioProc.PitchRange = AudioBank->PitchRange; }
	AudioPlayer.Initialize(this, AudioBank, 8);
	SetupPresentation();

	Clock->Initialize(Sim, 10);
	Clock->OnControlStep.BindUObject(this, &AStreetballWorld::OnControlStep);
	Clock->OnPhysicsStep.BindUObject(this, &AStreetballWorld::OnPhysicsStep);
	{
		// first episode starts like every later one: tiers 1-2 keep the ball away from the feet
		FStreetballResetSpec Start; Start.Reason = TEXT("startup");
		Director->PrepareReset(Director->GetProgress().ActiveTier, Start);
		if (Start.bPlaceBall || Start.bDribbleStart) ApplyReset(Start);
	}
	bReady = true;
	UpdateVisuals();
	UE_LOG(LogStreetball, Log, TEXT("World ready: %d geom actors, %d trained policies (%s), fallback %s"),
		GeomActors.Num(), RealPolicies.Num(), *FString::Join(RealPolicies, TEXT(",")), Fallback ? TEXT("loaded") : TEXT("none"));
	return true;
}

namespace
{
	/** One capture job from -StreetballCapture=<t>:<dur>:<fps>:<view>:<name>+... (dur 0 = a single still). */
	struct FCaptureJob
	{
		float T = 0.f, Dur = 0.f, Fps = 10.f;
		FString View, Name;
		int32 Frame = 0;
		float NextT = 0.f;
	};
}

void AStreetballWorld::UpdateCaptureSchedule()
{
	// Deterministic captures for the UU_AGENT before/after reports and the feature page (SCREENSHOTS/):
	//   -StreetballCapture=8:0:0:close:face+12:4:12:hoop:drop   -> Saved/Screenshots/cap_<name>_<frame>.png
	//   views: bc (broadcast, untouched), close (face), body (full body), hoop (east rim), high (neighbourhood), street
	//   -StreetballDemoDrop=12,30   drop the ball onto the east rim through the normal reset API (real contacts)
	//   -StreetballQuitAfter=40
	static bool bParsed = false;
	static TArray<FCaptureJob> Jobs;
	static TArray<float> Drops;
	static float QuitAfter = -1.f;
	if (!bParsed)
	{
		bParsed = true;
		FString List;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballCapture="), List, false))
		{
			TArray<FString> Items;
			List.ParseIntoArray(Items, TEXT("+"));
			for (const FString& It : Items)
			{
				TArray<FString> F;
				It.ParseIntoArray(F, TEXT(":"), false);
				if (F.Num() < 5) continue;
				FCaptureJob J;
				J.T = FCString::Atof(*F[0]); J.Dur = FCString::Atof(*F[1]); J.Fps = FMath::Max(1.f, FCString::Atof(*F[2]));
				J.View = F[3]; J.Name = F[4]; J.NextT = J.T;
				Jobs.Add(J);
			}
		}
		FString DropList;
		if (FParse::Value(FCommandLine::Get(), TEXT("StreetballDemoDrop="), DropList, false))
		{
			TArray<FString> Parts;
			DropList.ParseIntoArray(Parts, TEXT(","));
			for (const FString& P : Parts) Drops.Add(FCString::Atof(*P));
		}
		FParse::Value(FCommandLine::Get(), TEXT("StreetballQuitAfter="), QuitAfter);
	}
	UWorld* W = GetWorld();
	if (!W || !W->IsGameWorld() || !Camera) return;
	const float T = W->GetTimeSeconds();

	for (int32 i = Drops.Num() - 1; i >= 0; --i)
	{
		if (T < Drops[i]) continue;
		FStreetballResetSpec Spec;
		Spec.bRequested = true;
		Spec.bPlaceBall = true;
		Spec.BallPos = FVector3d(12.425 - 0.21, 0.06, 4.6);
		Spec.Reason = TEXT("demo: ball dropped onto the east rim");
		ApplyReset(Spec);
		Drops.RemoveAt(i);
	}

	const FTrackedState& S = Tracker->State();
	const auto ToUE = [](const FVector3d& P) { return FVector(P.X * 100.0, -P.Y * 100.0, P.Z * 100.0); };
	for (FCaptureJob& J : Jobs)
	{
		const bool bActive = T >= J.T - 0.6f && T <= J.T + J.Dur + 0.05f && J.Frame >= 0;
		if (!bActive) continue;
		// camera override (applied after the broadcast camera's own update this frame)
		FVector3d From, To;
		bool bOverride = true;
		const FVector3d Fwd(S.HeadingFwd.X, S.HeadingFwd.Y, 0.0), Left(S.HeadingLeft.X, S.HeadingLeft.Y, 0.0);
		if (J.View == TEXT("close")) { const FVector3d Head = S.PelvisPos + FVector3d(0, 0, 0.66); From = Head + 1.15 * Fwd + 0.4 * Left + FVector3d(0, 0, 0.04); To = Head - FVector3d(0, 0, 0.02); }
		else if (J.View == TEXT("body")) { From = S.PelvisPos + 2.7 * Fwd + 1.3 * Left + FVector3d(0, 0, 0.2); To = S.PelvisPos + FVector3d(0, 0, -0.05); }
		else if (J.View == TEXT("hoop")) { From = FVector3d(9.2, -2.4, 3.55); To = FVector3d(12.42, 0.0, 2.75); }
		else if (J.View == TEXT("high")) { From = FVector3d(-4.0, -36.0, 17.0); To = FVector3d(0.0, -4.0, 0.0); }
		else if (J.View == TEXT("street")) { From = FVector3d(-9.0, -12.2, 1.7); To = FVector3d(6.0, -24.0, 4.5); }
		else bOverride = false;
		if (bOverride)
		{
			const FVector P = ToUE(From);
			Camera->SetActorLocationAndRotation(P, FRotationMatrix::MakeFromX(ToUE(To) - P).Rotator());
		}
		if (T >= J.NextT && T >= J.T)
		{
			const FString File = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Screenshots"),
				FString::Printf(TEXT("cap_%s_%03d.png"), *J.Name, J.Frame)));
			FScreenshotRequest::RequestScreenshot(File, true, false);
			if (J.Frame == 0)
			{
				UE_LOG(LogStreetball, Log, TEXT("Capture %s (%s) starts at %.1f s, state %s"), *J.Name, *J.View, T, *UStreetballDirector::StateName(Director->GetState()));
			}
			++J.Frame;
			J.NextT = J.T + J.Frame / J.Fps;
			if (J.Dur <= 0.f) J.Frame = -1 - J.Frame;      // a still: done
		}
	}

	if (QuitAfter > 0.f && T >= QuitAfter)
	{
		QuitAfter = -1.f;
		UE_LOG(LogStreetball, Log, TEXT("Capture schedule done: voice lines %d, fx bursts %d, net kicks %d, makes %d, misses %d, scrambles %d, saves %d, jumps %d"),
			Voice.GetLinesPlayed(), FXPlayer.PlayedCount, FXPlayer.NetKicks, PresentationCounts[(int32)EPresentationEvent::Make],
			PresentationCounts[(int32)EPresentationEvent::Miss], PresentationCounts[(int32)EPresentationEvent::ScrambleStart],
			PresentationCounts[(int32)EPresentationEvent::ScrambleSave], PresentationCounts[(int32)EPresentationEvent::Jump]);
		FPlatformMisc::RequestExit(false);
	}
}

void AStreetballWorld::SetupPresentation()
{
	EventDetector.Reset();
	PendingPresentation.Reset();
	PendingPresentation.Reserve(32);
	for (int32& N : PresentationCounts) N = 0;
	if (!bPresentation || FParse::Param(FCommandLine::Get(), TEXT("StreetballNoPresentation")))
	{
		// also hide the PCG neighbourhood (its generated instances are components of the tagged volume)
		if (UWorld* W = GetWorld())
		{
			for (TActorIterator<AActor> It(W); It; ++It)
			{
				if (It->ActorHasTag(TEXT("StreetballNeighbourhood"))) It->SetActorHiddenInGame(true);
			}
		}
		UE_LOG(LogStreetball, Log, TEXT("Presentation: off"));
		return;
	}
	const FTrackedState& S = Tracker->State();
	const FVector Rims[2] = {
		FVector(S.RimPos[0].X * 100.0, -S.RimPos[0].Y * 100.0, S.RimPos[0].Z * 100.0),
		FVector(S.RimPos[1].X * 100.0, -S.RimPos[1].Y * 100.0, S.RimPos[1].Z * 100.0) };
	FXBank = FXBankPath.IsEmpty() ? nullptr : LoadObject<UCourtFXBank>(nullptr, *FXBankPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	FXPlayer.Initialize(this, FXBank, Rims, 4);
	VoiceBank = VoiceBankPath.IsEmpty() ? nullptr : LoadObject<UGrandmaVoiceBank>(nullptr, *VoiceBankPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	// The CC face morphs live on the grandma body mesh; other skins simply ignore unknown morph names.
	Voice.Initialize(this, Character ? Character->GetFaceMesh() : nullptr, VoiceBank, DirectorSeed);
	AudioPlayer.StartAmbience(this);
	UE_LOG(LogStreetball, Log, TEXT("Presentation: fx bank %s, voice %d lines, ambience %s, %d material overrides, grooms %d, cloth %s"),
		FXBank ? TEXT("loaded") : TEXT("missing"), VoiceBank ? VoiceBank->Lines.Num() : 0,
		AudioPlayer.IsAmbiencePlaying() ? TEXT("on") : TEXT("off"), MaterialOverrideCount,
		Character ? Character->NumGrooms() : 0, (Character && Character->HasCloth()) ? TEXT("yes") : TEXT("no"));
}

void AStreetballWorld::UpdatePresentation(float Dt)
{
	UWorld* W = GetWorld();
	const double Now = W ? W->GetTimeSeconds() : 0.0;
	const FTrackedState& S = Tracker->State();
	const auto ToUE = [](const FVector3d& P) { return FVector(P.X * 100.0, -P.Y * 100.0, P.Z * 100.0); };
	const auto NearestRim = [&S](const FVector3d& P) { return (P - S.RimPos[0]).SizeSquared() <= (P - S.RimPos[1]).SizeSquared() ? 0 : 1; };

	// contact events -> bursts, net knocks, pigeons
	for (const FCourtAudioEvent& E : PendingEvents)
	{
		FCourtFXCue Cue;
		if (FXPlayer.GetMapping().FromAudioEvent(E, Cue)) FXPlayer.Play(Cue);
		const FVector3d PSim(E.PositionUE.X / 100.0, -E.PositionUE.Y / 100.0, E.PositionUE.Z / 100.0);
		if (E.Kind == ECourtSound::BallRim || E.Kind == ECourtSound::BallBoard) FXPlayer.KickNet(NearestRim(PSim), false, Now);
		if (E.Kind == ECourtSound::BallFloor) FXPlayer.NotifyBallLanding(E.PositionUE, Now);
	}

	// game events -> voice, crowd, grunts, sweat, net swish
	for (const EPresentationEvent Ev : PendingPresentation)
	{
		++PresentationCounts[(int32)Ev];
		switch (Ev)
		{
		case EPresentationEvent::Make:
			AudioPlayer.Play(AudioProc.MakeEvent(ECourtSound::CrowdCheer, S.Time, S.RimPos[NearestRim(S.BallPos)], 6.f, TEXT("crowd")));
			FXPlayer.KickNet(NearestRim(S.BallPos), true, Now);
			break;
		case EPresentationEvent::Miss:
		case EPresentationEvent::Fall:
			AudioPlayer.Play(AudioProc.MakeEvent(ECourtSound::CrowdGroan, S.Time, S.PelvisPos, 4.f, TEXT("crowd")));
			break;
		case EPresentationEvent::ScrambleSave:
		{
			AudioPlayer.Play(AudioProc.MakeEvent(ECourtSound::CrowdCheer, S.Time, S.PelvisPos, 3.f, TEXT("crowd")));
			FCourtFXCue Sweat; Sweat.Fx = ECourtFX::Sweat; Sweat.PositionUE = ToUE(S.PelvisPos) + FVector(0, 0, 85.0); Sweat.Scale = 1.f;
			FXPlayer.Play(Sweat);
			break;
		}
		case EPresentationEvent::Jump:
		{
			AudioPlayer.Play(AudioProc.MakeEvent(ECourtSound::Grunt, S.Time, S.PelvisPos + FVector3d(0, 0, 0.7), 5.f, TEXT("grunt")));
			FCourtFXCue Sweat; Sweat.Fx = ECourtFX::Sweat; Sweat.PositionUE = ToUE(S.PelvisPos) + FVector(0, 0, 85.0); Sweat.Scale = 0.7f;
			FXPlayer.Play(Sweat);
			break;
		}
		default: break;
		}
		if (Voice.OnEvent(Ev, Now)) EventDetector.MarkActivity(S.Time);
	}
	PendingPresentation.Reset();

	Voice.Tick(Now, Dt);
	if (HUD) HUD->SetSubtitle(Now < Voice.GetSubtitleUntil() ? Voice.GetSubtitle() : FString());
}

void AStreetballWorld::ApplyReset(const FStreetballResetSpec& Spec)
{
	++ResetCount;
	Sim->ResetToKeyframe(KeyframeName);
	TArray<double>& Q = QBuf;                    // pre-sized in Setup: no allocation here
	const TConstArrayView<double> Q0 = Sim->QPos();
	FMemory::Memcpy(Q.GetData(), Q0.GetData(), Q.Num() * sizeof(double));
	const int32 R = RootQAdr, B = BallQAdr;
	if (Spec.bOffsetRoot)
	{
		Q[R] = Spec.RootXY.X; Q[R + 1] = Spec.RootXY.Y;
		Q[R + 3] = FMath::Cos(Spec.RootYaw / 2); Q[R + 4] = 0; Q[R + 5] = 0; Q[R + 6] = FMath::Sin(Spec.RootYaw / 2);
	}
	if (Spec.bPlaceBall)
	{
		Q[B] = Spec.BallPos.X; Q[B + 1] = Spec.BallPos.Y; Q[B + 2] = Spec.BallPos.Z;
		Q[B + 3] = 1; Q[B + 4] = Q[B + 5] = Q[B + 6] = 0;
	}
	for (double& v : VBuf) v = 0.0;
	if (Spec.bDribbleStart)
	{
		// sim l2_dribble.on_reset: spot = root + fwd * DribbleSpotFwd - hand * DribbleSpotSide * left (heading frame)
		const double w = Q[R + 3], x = Q[R + 4], y = Q[R + 5], z = Q[R + 6];
		double fx = 1 - 2 * (y * y + z * z), fy = 2 * (x * y + w * z);
		const double n = FMath::Sqrt(fx * fx + fy * fy);
		if (n < 1e-6) { fx = 1; fy = 0; } else { fx /= n; fy /= n; }
		const FVector2d Fwd(fx, fy), Left(-fy, fx);
		const FVector2d Spot = FVector2d(Q[R], Q[R + 1]) + Spec.DribbleSpotFwd * Fwd - Spec.DribbleHand * Spec.DribbleSpotSide * Left;
		Q[B] = Spot.X; Q[B + 1] = Spot.Y; Q[B + 2] = Spec.BallStartZ;
		Q[B + 3] = 1; Q[B + 4] = Q[B + 5] = Q[B + 6] = 0;
		VBuf[BallVAdr + 2] = Spec.BallStartVz;
	}
	Sim->SetQPos(Q);
	Sim->SetQVel(VBuf);
	Sim->SetCtrl(HoldCtrl);
	Sim->Forward();
	if (Character && Character->Mesh) Character->Mesh->ForceClothNextUpdateTeleportAndReset();
	Tracker->ResetState();
	Director->NotifyResetApplied(Tracker->State());
	if (Director->GetProgress().ActiveTier >= 3) Tracker->GrantControl();   // ball starts at the hand
	for (float& A : PrevAction) A = 0.f;
	EpisodeReward = 0.f;
	if (Clock) Clock->Resnapshot();
	++UnloggedResets;                            // logged from Tick, outside the control step
	LastResetReason = Spec.Reason;
}

void AStreetballWorld::OnControlStep(UMuJoCoSim* InSim)
{
	const double Dt = Clock ? Clock->GetTimestep() * Clock->GetSubstepsPerControl() : 0.02;
	const FTrackedState& S = Tracker->Update(Dt);
	Director->Update(S, Dt, DirOut);
	EventDetector.Update(S, DirOut, Director->GetProgress(), Director->GetState(), PendingPresentation);   // pre-reserved, read only
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
	FName ActivePolicyName = DirOut.PolicyName;
	if (ForcedPolicyIndex != INDEX_NONE && PolicyOrder.IsValidIndex(ForcedPolicyIndex))
	{
		ActivePolicyName = PolicyOrder[ForcedPolicyIndex];
	}
	UPolicyRunner* Policy = nullptr;
	if (TObjectPtr<UPolicyRunner>* Found = Policies.Find(ActivePolicyName)) Policy = Found->Get();
	LastPolicyName = ActivePolicyName;
	EpisodeReward += static_cast<float>(Dt * (S.InControl ? 1.0 : 0.1));
	if (Policy && ObsBuilder.IsInitialized())
	{
		// UU_AGENT hand-over rule: PrevAction is passed through unchanged across policy switches.
		const FTrackedState& T = Tracker->State();
		ObsBuilder.Compute(InSim, PrevAction, TConstArrayView<float>(DirOut.Task, 12), T.InControl ? 1.f : 0.f, T.CountdownFrac, Obs);
		if (Policy->Run(Obs, Action))
		{
			for (float& Val : Action)
			{
				if (!FMath::IsFinite(Val))
				{
					++NanInfCount;
					Val = 0.f;
				}
			}
			ObsBuilder.ActionToCtrl(Action, CtrlBuf);   // pre-sized member: no allocation
			InSim->SetCtrl(CtrlBuf);
			FMemory::Memcpy(PrevAction.GetData(), Action.GetData(), PrevAction.Num() * sizeof(float));
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

	if (DeltaSeconds > 1e-4f)
	{
		SmoothedFps = FMath::Lerp(SmoothedFps, 1.f / DeltaSeconds, 0.1f);
	}

	if (UWorld* W = GetWorld())
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(W, 0))
		{
			if (PC->WasInputKeyJustPressed(EKeys::F1)) CycleAppMode();
			if (PC->WasInputKeyJustPressed(EKeys::F2)) CycleCameraMode();
			if (PC->WasInputKeyJustPressed(EKeys::F3)) ToggleTelemetry();
			if (PC->WasInputKeyJustPressed(EKeys::F4)) CyclePolicyOverride();
			if (PC->WasInputKeyJustPressed(EKeys::SpaceBar)) TogglePause();
			if (PC->WasInputKeyJustPressed(EKeys::R)) ResetEpisode();

			if (Camera && Camera->GetCameraMode() == EStreetballCameraMode::Free)
			{
				FVector Move(0.f);
				const float Speed = 450.f * DeltaSeconds;
				if (PC->IsInputKeyDown(EKeys::W) || PC->IsInputKeyDown(EKeys::Up)) Move += Camera->GetActorForwardVector() * Speed;
				if (PC->IsInputKeyDown(EKeys::S) || PC->IsInputKeyDown(EKeys::Down)) Move -= Camera->GetActorForwardVector() * Speed;
				if (PC->IsInputKeyDown(EKeys::D) || PC->IsInputKeyDown(EKeys::Right)) Move += Camera->GetActorRightVector() * Speed;
				if (PC->IsInputKeyDown(EKeys::A) || PC->IsInputKeyDown(EKeys::Left)) Move -= Camera->GetActorRightVector() * Speed;
				if (!Move.IsNearlyZero()) Camera->AddFreeOffset(Move);
			}
		}
	}

	if (!bPaused)
	{
		Clock->Advance(DeltaSeconds);
	}
	if (UnloggedResets > 0)
	{
		const int32 Tier = Director->GetProgress().ActiveTier;
		const TCHAR* HandName = (Tier == 3 || Tier == 4) ? (Director->GetHand() > 0 ? TEXT("right") : TEXT("left")) : TEXT("n/a");
		UE_LOG(LogStreetball, Log, TEXT("Reset #%d applied (%s)%s in tier %d, dribble hand %s%s"), ResetCount, LastResetReason,
			UnloggedResets > 1 ? TEXT(" [+earlier this frame]") : TEXT(""), Tier, HandName,
			Director->ForcedHand != 0.0 ? TEXT(" (forced)") : TEXT(""));
		UnloggedResets = 0;
	}
	UpdateVisuals();
	UpdateCameraAndHUD(DeltaSeconds);
	UpdatePresentation(DeltaSeconds);
	UpdateCaptureSchedule();
	for (const FCourtAudioEvent& E : PendingEvents)
	{
		AudioPlayer.Play(E);
		RecentEvents.Add(E);
	}
	if (RecentEvents.Num() > 64) RecentEvents.RemoveAt(0, RecentEvents.Num() - 64, EAllowShrinking::No);
	PendingEvents.Reset();
}

EStreetballAppMode AStreetballWorld::CycleAppMode()
{
	AppMode = static_cast<EStreetballAppMode>((static_cast<int32>(AppMode) + 1) % 3);
	return AppMode;
}

void AStreetballWorld::CycleCameraMode()
{
	if (Camera) Camera->CycleCameraMode();
}

void AStreetballWorld::ToggleTelemetry()
{
	if (HUD) HUD->SetTelemetryVisible(!HUD->IsTelemetryVisible());
}

void AStreetballWorld::CyclePolicyOverride()
{
	if (PolicyOrder.Num() == 0)
	{
		ForcedPolicyIndex = INDEX_NONE;
		return;
	}
	if (ForcedPolicyIndex == INDEX_NONE)
	{
		ForcedPolicyIndex = 0;
	}
	else if (ForcedPolicyIndex + 1 >= PolicyOrder.Num())
	{
		ForcedPolicyIndex = INDEX_NONE; // return to director auto-selection
	}
	else
	{
		++ForcedPolicyIndex;
	}
}

void AStreetballWorld::ResetEpisode()
{
	FStreetballResetSpec Spec;
	Spec.bRequested = true;
	Spec.Reason = TEXT("manual reset (R)");
	ApplyReset(Spec);
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
	if (HUD)
	{
		HUD->UpdateFromProgress(Director->GetProgress(), Director->GetState());
		const FString ModeLabel = AppMode == EStreetballAppMode::Play ? TEXT("Play")
		                        : AppMode == EStreetballAppMode::Testbed ? TEXT("Testbed")
		                        : TEXT("Watch");
		FString CamLabel = TEXT("Broadcast");
		if (Camera)
		{
			switch (Camera->GetCameraMode())
			{
			case EStreetballCameraMode::Follow: CamLabel = TEXT("Follow"); break;
			case EStreetballCameraMode::Orbit: CamLabel = TEXT("Orbit"); break;
			case EStreetballCameraMode::Free: CamLabel = TEXT("Free"); break;
			default: break;
			}
		}
		const bool bUsingReal = RealPolicies.Contains(LastPolicyName.ToString());
		const FString PolicyLabel = LastPolicyName.IsNone() ? TEXT("fallback") : LastPolicyName.ToString();
		HUD->UpdateTelemetry(ModeLabel, CamLabel, PolicyLabel, DirectorSeed, EpisodeReward, NanInfCount, SmoothedFps, bPaused, !bUsingReal);
	}
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
