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
#include "StreetballShowcase.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
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
#include "Engine/Texture.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
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
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> Manny(TEXT("/Game/Project/Agents/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple"));
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
		TSharedPtr<FJsonObject> MH;
		if (!FParse::Param(FCommandLine::Get(), TEXT("StreetballNoMetaHuman")) && LoadMetaHumanParts(MH)) Candidates.Add(MH->GetStringField(TEXT("body")));
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

bool AStreetballCharacter::LoadMetaHumanParts(TSharedPtr<FJsonObject>& Out)
{
	FString Text;
	const FString Path = FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Art/Exports/GrandmaMH/parts.json"));
	return FFileHelper::LoadFileToString(Text, *Path) && FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Out) && Out.IsValid()
		&& Out->HasTypedField<EJson::String>(TEXT("body"));
}

void AStreetballCharacter::AttachMetaHuman(const TSharedPtr<FJsonObject>& Parts)
{
	// Outfit: skinned to the same re-proportioned skeleton, follows the driven body bone for bone.
	if (USkeletalMesh* O = LoadObject<USkeletalMesh>(nullptr, *Parts->GetStringField(TEXT("outfit")), nullptr, LOAD_NoWarn | LOAD_Quiet))
	{
		OutfitMesh = NewObject<USkeletalMeshComponent>(this, TEXT("MetaHumanOutfit"));
		OutfitMesh->SetupAttachment(Mesh);
		OutfitMesh->SetSkeletalMeshAsset(O);
		OutfitMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		OutfitMesh->SetLeaderPoseComponent(Mesh);
		OutfitMesh->RegisterComponent();
	}
	// Face: the native MetaHuman head (RigLogic DNA kept); ABP_Face copies body bones from its attach parent and keeps
	// the facial joints in their own local space, so the head follows the physics-driven neck.
	FString FacePath, AnimPath;
	if (Parts->TryGetStringField(TEXT("face"), FacePath))
	{
		if (USkeletalMesh* F = LoadObject<USkeletalMesh>(nullptr, *FacePath, nullptr, LOAD_NoWarn | LOAD_Quiet))
		{
			FaceMesh = NewObject<USkeletalMeshComponent>(this, TEXT("MetaHumanFace"));
			FaceMesh->SetupAttachment(Mesh);
			FaceMesh->SetSkeletalMeshAsset(F);
			FaceMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			FaceMesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
			if (Parts->TryGetStringField(TEXT("face_anim_class"), AnimPath))
				if (UClass* C = LoadObject<UClass>(nullptr, *AnimPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
				{
					FaceMesh->SetAnimationMode(EAnimationMode::AnimationBlueprint);
					FaceMesh->SetAnimInstanceClass(C);
				}
			FaceMesh->RegisterComponent();
			// mesh tick after the body, so the copied pose is this frame's
			FaceMesh->AddTickPrerequisiteComponent(Mesh);
		}
	}
	const TSharedPtr<FJsonObject>* Grooms_ = nullptr;
	if (FaceMesh && Parts->TryGetObjectField(TEXT("grooms"), Grooms_))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& G : (*Grooms_)->Values)
		{
			const TSharedPtr<FJsonObject> O = G.Value->AsObject();
			UGroomAsset* GA = LoadObject<UGroomAsset>(nullptr, *O->GetStringField(TEXT("groom")), nullptr, LOAD_NoWarn | LOAD_Quiet);
			UGroomBindingAsset* B = LoadObject<UGroomBindingAsset>(nullptr, *O->GetStringField(TEXT("binding")), nullptr, LOAD_NoWarn | LOAD_Quiet);
			if (!GA || !B) continue;
			UGroomComponent* GC = NewObject<UGroomComponent>(this, *FString::Printf(TEXT("MetaHuman%s"), *G.Key));
			GC->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			if (!FParse::Param(FCommandLine::Get(), TEXT("StreetballGroomBinding")))
			{
				// Rigid on the face's head bone (strands are authored in the face's bind-pose space). The mesh binding
				// renders nothing on this setup (2026-11-24: bound grooms invisible with or without the skin cache and a
				// forced LOD, while Epic's own Blueprint renders them); a short bob does not need to deform with the face.
				const FReferenceSkeleton& Ref = FaceMesh->GetSkeletalMeshAsset()->GetRefSkeleton();
				FTransform HeadCS = FTransform::Identity;
				for (int32 b = Ref.FindBoneIndex(TEXT("head")); b != INDEX_NONE; b = Ref.GetParentIndex(b)) HeadCS = HeadCS * Ref.GetRefBonePose()[b];
				GC->SetupAttachment(FaceMesh, TEXT("head"));
				GC->SetRelativeTransform(HeadCS.Inverse());
				GC->SetGroomAsset(GA);
				// Without a binding the automatic LOD switch crashed the game at the first close-up camera cut (the
				// close LODs expect a skinned binding); hold one card LOD. -StreetballGroomLOD=<n> overrides.
				int32 RigidLOD = 5; // 5-7 are the rigid helmet meshes; the card LODs (0-4) render nothing without a binding
				FParse::Value(FCommandLine::Get(), TEXT("StreetballGroomLOD="), RigidLOD);
				GC->SetForcedLOD(RigidLOD);
			}
			else
			{
				GC->SetupAttachment(FaceMesh);
				GC->SetGroomAsset(GA, B);
			}
			// The Blueprint's component override materials (hair colour, cards, helmet); without them nothing renders.
			const TArray<TSharedPtr<FJsonValue>>* Mats = nullptr;
			if (O->TryGetArrayField(TEXT("materials"), Mats))
				for (int32 m = 0; m < Mats->Num(); ++m)
					if (UMaterialInterface* MI = LoadObject<UMaterialInterface>(nullptr, *(*Mats)[m]->AsString(), nullptr, LOAD_NoWarn | LOAD_Quiet))
						GC->SetMaterial(m, MI);
			GC->RegisterComponent();
			Grooms.Add(GC);
			UE_LOG(LogStreetball, Log, TEXT("Character: MetaHuman groom %s: asset %s, binding %s (target %s), %d LODs, visible %d"),
				*G.Key, *GA->GetName(), *B->GetName(), B->GetTargetSkeletalMesh() ? *B->GetTargetSkeletalMesh()->GetName() : TEXT("none"),
				GA->GetLODCount(), GC->IsVisible() ? 1 : 0);
		}
	}
	// Debug: the assembled Blueprint itself, 1.5 m to the side, to compare hair/skin with Epic's own setup.
	if (FParse::Param(FCommandLine::Get(), TEXT("StreetballMetaHumanBP")))
		if (UClass* BPC = LoadObject<UClass>(nullptr, TEXT("/Game/Project/Agents/GrandmaMH/Build/MHC_Grandma/BP_MHC_Grandma.BP_MHC_Grandma_C"), nullptr, LOAD_NoWarn | LOAD_Quiet))
			GetWorld()->SpawnActor<AActor>(BPC, FTransform(FRotator(0, 90, 0), GetActorLocation() + FVector(0, 150, 0)));
	UE_LOG(LogStreetball, Log, TEXT("Character: MetaHuman grandma (outfit %s, face %s, %d grooms)"),
		OutfitMesh ? TEXT("yes") : TEXT("no"), FaceMesh ? TEXT("yes") : TEXT("no"), Grooms.Num());
}

void AStreetballCharacter::AttachExtras()
{
	const USkeletalMesh* SM = Mesh->GetSkeletalMeshAsset();
	TSharedPtr<FJsonObject> MH;
	if (SM && LoadMetaHumanParts(MH) && SM->GetPathName() == MH->GetStringField(TEXT("body")))
	{
		AttachMetaHuman(MH);
		return;
	}
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
	GeomMaterialOverrides.Add(TEXT("floor"), TEXT("/Game/Project/Environments/Materials/MI_CourtAsphalt.MI_CourtAsphalt"));
	GeomMaterialOverrides.Add(TEXT("ball"), TEXT("/Game/Project/Environments/Materials/MI_Basketball.MI_Basketball"));
	GeomMaterialOverrides.Add(TEXT("rim_bracket"), TEXT("/Game/Project/Environments/Materials/MI_SteelPaint.MI_SteelPaint"));
	GeomMaterialOverrides.Add(TEXT("rim_"), TEXT("/Game/Project/Environments/Materials/MI_RimPaint.MI_RimPaint"));
	GeomMaterialOverrides.Add(TEXT("board_"), TEXT("/Game/Project/Environments/Materials/MI_Backboard.MI_Backboard"));
	GeomMaterialOverrides.Add(TEXT("pole_"), TEXT("/Game/Project/Environments/Materials/MI_SteelPaint.MI_SteelPaint"));
	GeomMaterialOverrides.Add(TEXT("arm_"), TEXT("/Game/Project/Environments/Materials/MI_SteelPaint.MI_SteelPaint"));
	GeomMaterialOverrides.Add(TEXT("fence_"), TEXT("/Game/Project/Environments/Materials/MI_ChainLink.MI_ChainLink"));
}

int32 AStreetballWorld::ApplyLocalScans()
{
	const FString Path = FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Art/megascans.json"));
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!FFileHelper::LoadFileToString(Text, *Path) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid()) return 0;
	const TSharedPtr<FJsonObject>* Targets = nullptr;
	if (!Root->TryGetObjectField(TEXT("targets"), Targets)) return 0;
	int32 Applied = 0;
	for (const TPair<FString, TSharedPtr<FJsonValue>>& T : (*Targets)->Values)
	{
		const TSharedPtr<FJsonObject> Cfg = T.Value->AsObject();
		TMap<FName, UTexture*> Textures;
		bool bAll = true;
		for (const TPair<FString, TSharedPtr<FJsonValue>>& P : Cfg->GetObjectField(TEXT("textures"))->Values)
		{
			UTexture* Tex = LoadObject<UTexture>(nullptr, *P.Value->AsString(), nullptr, LOAD_NoWarn | LOAD_Quiet);
			if (!Tex) { bAll = false; break; }
			Textures.Add(FName(*P.Key), Tex);
		}
		if (!bAll) continue; // not imported on this machine (fresh clone): keep the procedural material
		UMaterialInstanceDynamic* MID = nullptr;
		for (TPair<FString, TObjectPtr<UMaterialInterface>>& O : LoadedOverrides)
		{
			if (!O.Value || O.Value->GetPathName() != T.Key) continue;
			if (!MID)
			{
				MID = UMaterialInstanceDynamic::Create(O.Value, this);
				for (const TPair<FName, UTexture*>& X : Textures) MID->SetTextureParameterValue(X.Key, X.Value);
				for (const TPair<FString, TSharedPtr<FJsonValue>>& S : Cfg->GetObjectField(TEXT("scalars"))->Values)
					MID->SetScalarParameterValue(FName(*S.Key), (float)S.Value->AsNumber());
			}
			O.Value = MID;
		}
		if (MID)
		{
			++Applied;
			UE_LOG(LogTemp, Log, TEXT("StreetballWorld: local Megascans applied to %s (%d textures)"), *T.Key, Textures.Num());
		}
	}
	return Applied;
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
	if (UStreetballShowcaseSubsystem* Showcase = UStreetballShowcaseSubsystem::Get(this))
	{
		Showcase->OnDemoModeChanged.AddUObject(this, &AStreetballWorld::HandleDemoMode);
		Showcase->OnDemoCamera.AddUObject(this, &AStreetballWorld::HandleDemoCamera);
	}
}

void AStreetballWorld::HandleDemoMode(bool bActive)
{
	if (bActive)
	{
		PreDemoAppMode = AppMode;
		PreDemoCameraMode = Camera ? static_cast<uint8>(Camera->GetCameraMode()) : 0;
		AppMode = EStreetballAppMode::Watch;   // the director hands every skill to the trained policies
		if (HUD) HUD->SetVisibility(ESlateVisibility::Collapsed);
	}
	else
	{
		AppMode = PreDemoAppMode;
		if (Camera) Camera->SetCameraMode(static_cast<EStreetballCameraMode>(PreDemoCameraMode));
		if (HUD) HUD->SetVisibility(ESlateVisibility::SelfHitTestInvisible);
	}
}

void AStreetballWorld::HandleDemoCamera(FName CameraName, int32 Index)
{
	if (!Camera) return;
	if (CameraName == TEXT("Follow")) Camera->SetCameraMode(EStreetballCameraMode::Follow);
	else if (CameraName == TEXT("Orbit")) Camera->SetCameraMode(EStreetballCameraMode::Orbit);
	else if (CameraName == TEXT("Free")) Camera->SetCameraMode(EStreetballCameraMode::Free);
	else Camera->SetCameraMode(EStreetballCameraMode::Broadcast);
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
	// Side-by-side comparisons: -StreetballPolicy_<family>=<file> (relative to Content/Project/RL_Policies, e.g. policies/locomotion_amp.onnx)
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
			FString Sidecar;
			TSharedPtr<FJsonObject> Meta;
			if (FFileHelper::LoadFileToString(Sidecar, *FPaths::ChangeExtension(Path, TEXT("json")))
				&& FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Sidecar), Meta) && Meta.IsValid())
			{
				Meta->TryGetStringField(TEXT("level"), R->Level);
			}
			UE_LOG(LogStreetball, Log, TEXT("Policy %s: trained model %s (level %s)"), *Family, *Path, R->Level.IsEmpty() ? TEXT("?") : *R->Level);
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
		LocalScanCount = ApplyLocalScans();
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
		FParse::Value(FCommandLine::Get(), TEXT("StreetballObsDump="), ObsDumpPath);
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
	static int32 FeatureStep = -1;
	if (!bParsed)
	{
		bParsed = true;
		if (FParse::Param(FCommandLine::Get(), TEXT("StreetballDemoFeatures"))) FeatureStep = 0;
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
		if (Jobs.Num() > 0)
		{
			// capture cameras cut every job; motion blur would smear those frames
			if (IConsoleVariable* MB = IConsoleManager::Get().FindConsoleVariable(TEXT("r.MotionBlurQuality"))) MB->Set(0, ECVF_SetByCode);
		}
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
	if (FeatureStep >= 0)
	{
		if (FeatureStep == 0 && T >= 3.0f)
		{
			FeatureStep = 1;
			AppMode = EStreetballAppMode::Play;
			JumpToTier(2);
			CommandCourtTarget(FVector2d(4.5, 1.5));
		}
		else if (FeatureStep == 1 && T >= 9.0f)
		{
			FeatureStep = 2;
			LobBallToAthlete();
		}
		else if (FeatureStep == 2 && T >= 12.5f)
		{
			FeatureStep = 3;
			AppMode = EStreetballAppMode::Testbed;
			JumpToTier(1);
			TimeScaleIdx = 1; // 0.50x slow-mo
			if (Clock) Clock->TimeScale = 0.5f;
			ApplyTestbedPush(FVector2d(1.0, 0.35), 110.f, 0.25f);
		}
		else if (FeatureStep == 3 && T >= 16.0f)
		{
			FeatureStep = 4;
			ApplyTestbedPush(FVector2d(-0.8, -0.6), 110.f, 0.25f);
		}
		else if (FeatureStep == 4 && T >= 21.0f)
		{
			FeatureStep = 5;
			TimeScaleIdx = 2; // 1.0x
			if (Clock) Clock->TimeScale = 1.0f;
			AppMode = EStreetballAppMode::Watch;
			JumpToTier(5);
		}
	}
	const auto ToUE = [](const FVector3d& P) { return FVector(P.X * 100.0, -P.Y * 100.0, P.Z * 100.0); };
	for (FCaptureJob& J : Jobs)
	{
		// a still waits until it is taken (a shader-compile hitch can jump past a short window); bursts end on time
		const bool bActive = J.Frame >= 0 && T >= J.T - 0.6f && (J.Dur <= 0.f || T <= J.T + J.Dur + 0.05f);
		if (!bActive) continue;
		// camera override (applied after the broadcast camera's own update this frame)
		FVector3d From, To;
		bool bOverride = true;
		const FVector3d Fwd(S.HeadingFwd.X, S.HeadingFwd.Y, 0.0), Left(S.HeadingLeft.X, S.HeadingLeft.Y, 0.0);
		if (J.View == TEXT("close")) { const FVector3d Head = S.PelvisPos + FVector3d(0, 0, 0.66); From = Head + 1.15 * Fwd + 0.4 * Left + FVector3d(0, 0, 0.04); To = Head - FVector3d(0, 0, 0.02); }
		else if (J.View == TEXT("body")) { From = S.PelvisPos + 3.6 * Fwd + 1.6 * Left + FVector3d(0, 0, 0.35); To = S.PelvisPos + FVector3d(0, 0, -0.1); }
		else if (J.View == TEXT("foot")) { From = S.PelvisPos + 0.65 * Fwd + 1.05 * Left - FVector3d(0, 0, 0.62); To = S.PelvisPos + 0.12 * Fwd - FVector3d(0, 0, 0.80); }
		else if (J.View == TEXT("crowd")) { From = FVector3d(0.0, 1.5, 2.1); To = FVector3d(0.0, 10.6, 1.35); }
		else if (J.View == TEXT("hoop")) { From = FVector3d(9.2, -2.4, 3.55); To = FVector3d(12.42, 0.0, 2.75); }
		else if (J.View == TEXT("high")) { From = FVector3d(-26.0, -23.0, 21.0); To = FVector3d(0.0, 0.0, 0.0); }
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
	Crowd.Initialize(GetWorld(), DirectorSeed, 16);
	AudioPlayer.StartAmbience(this);
	UE_LOG(LogStreetball, Log, TEXT("Presentation: fx bank %s, voice %d lines, crowd %d, ambience %s, %d material overrides, grooms %d, cloth %s"),
		FXBank ? TEXT("loaded") : TEXT("missing"), VoiceBank ? VoiceBank->Lines.Num() : 0, Crowd.NumSpectators(),
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
		Crowd.OnEvent(Ev, Now);
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

	// #3 Torque-driven exertion morphs, breathing & sweat
	if (Sim && Sim->IsLoaded())
	{
		LastPowerW = Sim->ComputeActuatorPowerWatts();
		const float TorqueNorm = Sim->ComputeMeanTorqueNorm();
		const float RawExertion = FMath::Clamp(0.6f * (LastPowerW / 600.f) + 0.4f * TorqueNorm, 0.f, 1.f);
		Exertion01 = FMath::Lerp(Exertion01, RawExertion, FMath::Clamp(Dt * 4.f, 0.f, 1.f));
		Voice.SetExertion(Exertion01);
		if (Exertion01 > 0.62f && Now >= NextExertionSweatT)
		{
			FCourtFXCue Sweat;
			Sweat.Fx = ECourtFX::Sweat;
			Sweat.PositionUE = ToUE(S.PelvisPos) + FVector(0, 0, 82.0);
			Sweat.Scale = 0.5f + 0.6f * Exertion01;
			FXPlayer.Play(Sweat);
			NextExertionSweatT = Now + 1.4;
		}
	}

	// #15 Sideline crowd tracking & mood animation
	const FVector FocusUE = (Director->GetProgress().ActiveTier >= 3) ? ToUE(S.BallPos) : ToUE(S.PelvisPos);
	Crowd.Tick(Now, FocusUE);

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
	Sim->ClearExternalForces();
	ActivePushForceSim = FVector2d::ZeroVector;
	PushRemainingS = 0.0;
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
	if (PushRemainingS > 0.0)
	{
		InSim->SetBodyExternalForceSim(PelvisBody, FVector3d(ActivePushForceSim.X, ActivePushForceSim.Y, 0.0));
		PushRemainingS -= Dt;
		if (PushRemainingS <= 0.0)
		{
			PushRemainingS = 0.0;
			ActivePushForceSim = FVector2d::ZeroVector;
			InSim->SetBodyExternalForceSim(PelvisBody, FVector3d::ZeroVector);
		}
	}
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
			if (UStreetballShowcaseSubsystem* Showcase = UStreetballShowcaseSubsystem::Get(this))
			{
				Showcase->ReportInferenceMs(static_cast<float>(Policy->LastInferenceMs));
				Showcase->SetCurriculumStage(Policy->Level.IsEmpty() ? ActivePolicyName.ToString() : Policy->Level);
			}
			for (float& Val : Action)
			{
				if (!FMath::IsFinite(Val))
				{
					++NanInfCount;
					Val = 0.f;
				}
			}
			if (!ObsDumpPath.IsEmpty() && ObsDumpRows < 150)
			{
				FString Row = FString::Printf(TEXT("%.6f"), InSim->GetSimTime());
				for (double v : InSim->QPos()) Row += FString::Printf(TEXT(",%.9g"), v);
				for (double v : InSim->QVel()) Row += FString::Printf(TEXT(",%.9g"), v);
				for (int32 k = 0; k < 12; ++k) Row += FString::Printf(TEXT(",%.6g"), DirOut.Task[k]);
				Row += FString::Printf(TEXT(",%d,%.6g"), T.InControl ? 1 : 0, T.CountdownFrac);
				for (float v : Obs) Row += FString::Printf(TEXT(",%.7g"), v);
				for (float v : Action) Row += FString::Printf(TEXT(",%.7g"), v);
				ObsDumpBuf += Row + TEXT("\n");
				if (++ObsDumpRows == 150)
				{
					FFileHelper::SaveStringToFile(ObsDumpBuf, *ObsDumpPath);
					UE_LOG(LogStreetball, Log, TEXT("ObsDump: wrote 150 control steps to %s (policy %s)"), *ObsDumpPath, *ActivePolicyName.ToString());
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
			if (PC->WasInputKeyJustPressed(EKeys::F1) || PC->WasInputKeyJustPressed(EKeys::M)) CycleAppMode();
			if (PC->WasInputKeyJustPressed(EKeys::F2) || PC->WasInputKeyJustPressed(EKeys::C)) CycleCameraMode();
			if (PC->WasInputKeyJustPressed(EKeys::F3) || PC->WasInputKeyJustPressed(EKeys::T)) ToggleTelemetry();
			if (PC->WasInputKeyJustPressed(EKeys::F4) || PC->WasInputKeyJustPressed(EKeys::P)) CyclePolicyOverride();
			if (PC->WasInputKeyJustPressed(EKeys::SpaceBar)) TogglePause();
			if (PC->WasInputKeyJustPressed(EKeys::R)) ResetEpisode();

			if (AppMode == EStreetballAppMode::Play || AppMode == EStreetballAppMode::Testbed)
			{
				if (PC->WasInputKeyJustPressed(EKeys::One)) JumpToTier(1);
				if (PC->WasInputKeyJustPressed(EKeys::Two)) JumpToTier(2);
				if (PC->WasInputKeyJustPressed(EKeys::Three)) JumpToTier(3);
				if (PC->WasInputKeyJustPressed(EKeys::Four)) JumpToTier(4);
				if (PC->WasInputKeyJustPressed(EKeys::Five)) JumpToTier(5);
			}

			PC->bShowMouseCursor = (AppMode == EStreetballAppMode::Play);
			if (AppMode == EStreetballAppMode::Play)
			{
				if (PC->WasInputKeyJustPressed(EKeys::LeftMouseButton))
				{
					FVector RayOrigin, RayDir;
					if (PC->DeprojectMousePositionToWorld(RayOrigin, RayDir) && FMath::Abs(RayDir.Z) > 1e-4)
					{
						const double T = -RayOrigin.Z / RayDir.Z;
						if (T > 0.0)
						{
							const FVector HitUE = RayOrigin + RayDir * T;
							CommandCourtTarget(FVector2d(HitUE.X / 100.0, -HitUE.Y / 100.0));
						}
					}
				}
				if (PC->WasInputKeyJustPressed(EKeys::RightMouseButton) || PC->WasInputKeyJustPressed(EKeys::B))
				{
					LobBallToAthlete();
				}
			}
			else if (AppMode == EStreetballAppMode::Testbed)
			{
				if (PC->WasInputKeyJustPressed(EKeys::I)) ApplyTestbedPush(FVector2d(1.0, 0.0));
				if (PC->WasInputKeyJustPressed(EKeys::K)) ApplyTestbedPush(FVector2d(-1.0, 0.0));
				if (PC->WasInputKeyJustPressed(EKeys::J)) ApplyTestbedPush(FVector2d(0.0, 1.0));
				if (PC->WasInputKeyJustPressed(EKeys::L)) ApplyTestbedPush(FVector2d(0.0, -1.0));
				if (PC->WasInputKeyJustPressed(EKeys::LeftBracket)) StepTimeScale(-1);
				if (PC->WasInputKeyJustPressed(EKeys::RightBracket)) StepTimeScale(1);
			}

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

void AStreetballWorld::JumpToTier(int32 Tier)
{
	if (!bReady || !Director) return;
	Tier = FMath::Clamp(Tier, 1, 5);
	Director->StartAtTier(Tier);
	FStreetballResetSpec Spec;
	Spec.bRequested = true;
	Spec.Reason = TEXT("tier jump");
	Director->PrepareReset(Tier, Spec);
	ApplyReset(Spec);
}

void AStreetballWorld::CommandCourtTarget(const FVector2d& SimXY)
{
	if (!bReady || !Director) return;
	Director->SetManualWaypoint(SimXY);
}

void AStreetballWorld::LobBallToAthlete()
{
	if (!bReady || !Sim || !Tracker || BallQAdr < 0 || BallVAdr < 0) return;
	const FTrackedState& S = Tracker->State();
	// Place ball 1.1 m ahead of athlete and toss gently toward chest height (~1.1 m)
	const FVector2d Fwd = S.HeadingFwd.Length() > 1e-4 ? S.HeadingFwd : FVector2d(1.0, 0.0);
	const FVector3d StartPos(S.PelvisPos.X + Fwd.X * 1.15, S.PelvisPos.Y + Fwd.Y * 1.15, 1.45);
	const double FlightT = 0.45;
	const FVector3d TargetPos(S.PelvisPos.X + Fwd.X * 0.25, S.PelvisPos.Y + Fwd.Y * 0.25, 1.05);
	const double Vx = (TargetPos.X - StartPos.X) / FlightT;
	const double Vy = (TargetPos.Y - StartPos.Y) / FlightT;
	const double Vz = (TargetPos.Z - StartPos.Z + 0.5 * 9.81 * FlightT * FlightT) / FlightT;

	const TConstArrayView<double> Q0 = Sim->QPos();
	const TConstArrayView<double> V0 = Sim->QVel();
	FMemory::Memcpy(QBuf.GetData(), Q0.GetData(), QBuf.Num() * sizeof(double));
	FMemory::Memcpy(VBuf.GetData(), V0.GetData(), VBuf.Num() * sizeof(double));
	QBuf[BallQAdr] = StartPos.X; QBuf[BallQAdr + 1] = StartPos.Y; QBuf[BallQAdr + 2] = StartPos.Z;
	QBuf[BallQAdr + 3] = 1.0; QBuf[BallQAdr + 4] = QBuf[BallQAdr + 5] = QBuf[BallQAdr + 6] = 0.0;
	VBuf[BallVAdr] = Vx; VBuf[BallVAdr + 1] = Vy; VBuf[BallVAdr + 2] = Vz;
	VBuf[BallVAdr + 3] = VBuf[BallVAdr + 4] = VBuf[BallVAdr + 5] = 0.0;
	Sim->SetQPos(QBuf);
	Sim->SetQVel(VBuf);
	Sim->Forward();
	if (Clock) Clock->Resnapshot();
}

void AStreetballWorld::ApplyTestbedPush(const FVector2d& DirSim, float ForceN, float DurationS)
{
	if (!bReady || PelvisBody < 0) return;
	const double Len = DirSim.Length();
	if (Len <= 1e-6) return;
	ActivePushForceSim = (DirSim / Len) * ForceN;
	PushRemainingS = FMath::Max(0.02, (double)DurationS);
}

void AStreetballWorld::StepTimeScale(int32 DeltaIndex)
{
	static constexpr float Scales[5] = { 0.25f, 0.5f, 1.0f, 1.5f, 2.0f };
	TimeScaleIdx = FMath::Clamp(TimeScaleIdx + DeltaIndex, 0, 4);
	if (Clock) Clock->TimeScale = Scales[TimeScaleIdx];
}

float AStreetballWorld::GetTimeScale() const
{
	return Clock ? Clock->TimeScale : 1.f;
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
		if (UStreetballShowcaseSubsystem* Showcase = UStreetballShowcaseSubsystem::Get(this)) Showcase->ReportEpisodeReward(EpisodeReward);
		HUD->UpdateTelemetry(ModeLabel, CamLabel, PolicyLabel, DirectorSeed, EpisodeReward, NanInfCount, SmoothedFps, bPaused, !bUsingReal,
			Exertion01, LastPowerW, GetTimeScale());
		if (AppMode == EStreetballAppMode::Play)
		{
			HUD->SetModeHint(TEXT("M/F1 Mode  |  LMB Waypoint  |  RMB/B Lob Ball  |  1-5 Tier  |  C/F2 Cam  |  Space Pause  |  R Reset"));
		}
		else if (AppMode == EStreetballAppMode::Testbed)
		{
			HUD->SetModeHint(TEXT("M/F1 Mode  |  IJKL Push 120N  |  [/] Speed  |  1-5 Tier  |  P/F4 Policy  |  T/F3 Telem  |  Tab Diag  |  R Reset"));
		}
		else
		{
			HUD->SetModeHint(TEXT("M/F1 Mode  |  C/F2 Camera  |  T/F3 Telemetry  |  Tab Diagnostics  |  P/F4 Policy  |  Space Pause  |  R Reset"));
		}
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
