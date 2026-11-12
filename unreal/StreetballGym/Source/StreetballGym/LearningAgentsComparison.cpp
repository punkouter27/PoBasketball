#include "LearningAgentsComparison.h"
#include "StreetballGym.h"
#include "StreetballAnimInstance.h"
#include "StreetballHUDWidget.h"
#include "MuJoCoBoneMapper.h"
#include "MuJoCoSim.h"
#include "ObsBuilder.h"
#include "LearningAgentsManager.h"
#include "LearningAgentsPolicy.h"
#include "LearningAgentsCritic.h"
#include "LearningAgentsPPOTrainer.h"
#include "LearningAgentsCommunicator.h"
#include "LearningNeuralNetwork.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/BoxComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SphereComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/Canvas.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpectatorPawn.h"
#include "GameFramework/WorldSettings.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformApplicationMisc.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "PhysicsEngine/PhysicsConstraintComponent.h"
#include "PhysicsEngine/PhysicsSettings.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/ConstructorHelpers.h"

namespace
{
	constexpr float ControlDt = 0.02f;
	constexpr int32 NumActions = FObsBuilder::NumAction;
	constexpr int32 NumObservations = FObsBuilder::NumObs;

	// Axial vectors reflect differently from positions: det(S) * S, with S = diag(1,-1,1).
	FVector AxialToUE(const double* V) { return FVector(-V[0], V[1], -V[2]); }
	FVector PolarToSim(const FVector& V) { return FVector(V.X, -V.Y, V.Z); }
	FVector AxialToSim(const FVector& V) { return FVector(-V.X, V.Y, -V.Z); }

	bool WriteJson(const TSharedRef<FJsonObject>& Object, const FString& Path)
	{
		FString Text;
		return FJsonSerializer::Serialize(Object, TJsonWriterFactory<>::Create(&Text))
			&& FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}

	bool AppendCsv(const FString& Text, const FString& Path)
	{
		return FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,
			&IFileManager::Get(), FILEWRITE_Append);
	}

	FQuat JointRotation(const TArray<FLAComparisonJoint>& Joints, const TArray<float>& Angles,
		const FLAComparisonBody& Body, int32 Stop = MAX_int32)
	{
		FQuat Q = FQuat::Identity;
		for (int32 j = 0; j < FMath::Min(Body.JointCount, Stop); ++j)
		{
			const int32 Index = Body.FirstJoint + j;
			Q = Q * FQuat(Joints[Index].Axis, Angles[Index]);
		}
		return Q;
	}
}

ALAComparisonAgent::ALAComparisonAgent()
{
	PrimaryActorTick.bCanEverTick = false;
	SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("Root")));
	Mesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Manny"));
	Mesh->SetupAttachment(RootComponent);
	Mesh->SetRelativeRotation(FRotator(0, -90, 0));
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetSimulatePhysics(false);
	Mesh->SetAnimationMode(EAnimationMode::AnimationBlueprint);
	Mesh->SetAnimInstanceClass(UStreetballAnimInstance::StaticClass());
	Mesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> Manny(TEXT("/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple"));
	if (Manny.Succeeded()) Mesh->SetSkeletalMeshAsset(Manny.Object);
}

bool ALAComparisonAgent::Initialize(UMuJoCoSim* Definition, const FVector& Origin, bool bRender)
{
	if (!Definition || !Definition->IsLoaded() || !Mesh->GetSkeletalMeshAsset()) return false;
	const mjModel* M = Definition->GetModel();
	FObsBuilder Spec;
	if (!Spec.Initialize(Definition, Streetball::ObsSpecPath())) return false;
	SetActorLocation(Origin);
	Definition->ResetData();
	const int32 PelvisId = Definition->BodyId(TEXT("pelvis"));
	const int32 EndBody = Definition->BodyId(TEXT("foot_r"));
	TMap<int32, int32> BodyIndices;
	UPhysicalMaterial* Material = NewObject<UPhysicalMaterial>(this);
	Material->Friction = 0.9f;
	Material->Restitution = 0;

	for (int32 b = PelvisId; b <= EndBody; ++b)
	{
		if (!M->body_geomnum[b]) continue;
		const int32 g = M->body_geomadr[b];
		FLAComparisonBody Body;
		Body.ModelBody = b;
		Body.ReferenceBody = Definition->GetBodyTransformUE(b);
		const FTransform Geom = Definition->GetGeomTransformUE(g);
		Body.GeomInBody = Geom.GetRelativeTransform(Body.ReferenceBody);
		int32 Parent = M->body_parentid[b];
		while (Parent > 0 && !BodyIndices.Contains(Parent)) Parent = M->body_parentid[Parent];
		Body.Parent = BodyIndices.FindRef(Parent);
		if (!BodyIndices.Contains(Parent)) Body.Parent = INDEX_NONE;
		const FVector Size = Definition->GetGeomSize(g) * 100;
		const FName Name(*FString::Printf(TEXT("Chaos_%s"), *Definition->BodyName(b)));
		switch (Definition->GetGeomType(g))
		{
		case mjGEOM_BOX:
		{
			UBoxComponent* Shape = NewObject<UBoxComponent>(this, Name);
			Shape->SetBoxExtent(Size);
			Body.Shape = Shape;
			break;
		}
		case mjGEOM_SPHERE:
		{
			USphereComponent* Shape = NewObject<USphereComponent>(this, Name);
			Shape->SetSphereRadius(Size.X);
			Body.Shape = Shape;
			break;
		}
		case mjGEOM_CAPSULE:
		{
			UCapsuleComponent* Shape = NewObject<UCapsuleComponent>(this, Name);
			Shape->SetCapsuleSize(Size.X, Size.X + Size.Y);
			Body.Shape = Shape;
			break;
		}
		default:
			UE_LOG(LogStreetball, Error, TEXT("LearningAgents: unsupported humanoid geom %d"), Definition->GetGeomType(g));
			return false;
		}
		Body.Shape->SetupAttachment(RootComponent);
		Body.Shape->SetMobility(EComponentMobility::Movable);
		Body.Shape->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
		Body.Shape->SetCollisionObjectType(ECC_PhysicsBody);
		Body.Shape->SetCollisionResponseToAllChannels(ECR_Block);
		Body.Shape->SetHiddenInGame(true);
		Body.Shape->SetLinearDamping(0);
		Body.Shape->SetAngularDamping(0);
		Body.Shape->SetPhysMaterialOverride(Material);
		Body.Shape->SetNotifyRigidBodyCollision(true);
		Body.Shape->OnComponentHit.AddDynamic(this, &ALAComparisonAgent::OnBodyHit);
		Body.Shape->BodyInstance.PositionSolverIterationCount = 16;
		Body.Shape->BodyInstance.VelocitySolverIterationCount = 4;
		Body.Shape->BodyInstance.bOverrideMass = true;
		Body.Shape->BodyInstance.SetMassOverride(float(M->body_mass[b]));
		Body.Shape->RegisterComponent();
		Body.Shape->SetWorldTransform(FTransform(Geom.GetRotation(), Origin + Geom.GetLocation()));
		Body.Shape->SetSimulatePhysics(true);
		Shapes.Add(Body.Shape);
		BodyIndices.Add(b, Bodies.Num());
		Body.FirstJoint = Joints.Num();
		for (int32 j = 0; j < M->body_jntnum[b]; ++j)
		{
			const int32 ModelJoint = M->body_jntadr[b] + j;
			if (M->jnt_type[ModelJoint] != mjJNT_HINGE) continue;
			const int32 ActionIndex = Spec.JointOrder.IndexOfByKey(Definition->JointName(ModelJoint));
			if (ActionIndex == INDEX_NONE) return false;
			FLAComparisonJoint Joint;
			Joint.Axis = AxialToUE(M->jnt_axis + 3 * ModelJoint);
			Joint.Body = Bodies.Num();
			Joint.LocalIndex = ActionIndex;
			Joint.Nominal = float(Spec.Nominal[ActionIndex]);
			// Use the actual XML limits; some were tightened after the original spec was frozen.
			Joint.Low = float(M->jnt_range[2 * ModelJoint]);
			Joint.High = float(M->jnt_range[2 * ModelJoint + 1]);
			Joint.Kp = float(M->actuator_gainprm[mjNGAIN * ActionIndex]);
			Joint.Kv = float(-M->actuator_biasprm[mjNBIAS * ActionIndex + 2]);
			Joint.MaxTorque = float(M->actuator_forcerange[2 * ActionIndex + 1]);
			Joints.Add(Joint);
			++Body.JointCount;
		}
		Bodies.Add(Body);
	}
	if (Bodies.Num() != 15 || Joints.Num() != NumActions) return false;
	Pelvis = BodyIndices.FindChecked(PelvisId);
	for (int32 Side = 0; Side < 2; ++Side)
	{
		Feet[Side] = BodyIndices.FindChecked(Definition->BodyId(Side == 0 ? TEXT("foot_l") : TEXT("foot_r")));
		Hands[Side] = BodyIndices.FindChecked(Definition->BodyId(Side == 0 ? TEXT("hand_l") : TEXT("hand_r")));
	}
	for (FLAComparisonBody& Body : Bodies)
	{
		if (Body.Parent == INDEX_NONE) continue;
		UPhysicsConstraintComponent* C = NewObject<UPhysicsConstraintComponent>(this);
		C->SetupAttachment(RootComponent);
		C->RegisterComponent();
		C->SetDisableCollision(true);
		C->SetProjectionEnabled(false);
		C->SetLinearXLimit(LCM_Locked, 0);
		C->SetLinearYLimit(LCM_Locked, 0);
		C->SetLinearZLimit(LCM_Locked, 0);
		FQuat Basis = FQuat::Identity;
		FQuat Center = FQuat::Identity;
		float Limits[3] = {0, 0, 0};
		if (Body.JointCount)
		{
			const FVector X = Joints[Body.FirstJoint].Axis;
			FVector Y, Z;
			X.FindBestAxisVectors(Y, Z);
			if (Body.JointCount > 1) Y = Joints[Body.FirstJoint + 1].Axis;
			Basis = FRotationMatrix::MakeFromXY(X, Y).ToQuat();
			for (int32 j = 0; j < Body.JointCount; ++j)
			{
				const FLAComparisonJoint& Joint = Joints[Body.FirstJoint + j];
				Limits[j] = FMath::RadiansToDegrees(0.5f * (Joint.High - Joint.Low));
				Center = Center * FQuat(Joint.Axis, 0.5f * (Joint.High + Joint.Low));
			}
		}
		C->SetAngularTwistLimit(Body.JointCount > 0 ? ACM_Limited : ACM_Locked, Limits[0]);
		C->SetAngularSwing2Limit(Body.JointCount > 1 ? ACM_Limited : ACM_Locked, Limits[1]);
		C->SetAngularSwing1Limit(Body.JointCount > 2 ? ACM_Limited : ACM_Locked, Limits[2]);
		Body.ConstraintBasis = Basis;
		Body.ConstraintCenter = Center;
		if (Body.JointCount)
		{
			const FLAComparisonJoint& Drive = Joints[Body.FirstJoint];
			for (int32 j = 1; j < Body.JointCount; ++j)
			{
				const FLAComparisonJoint& Joint = Joints[Body.FirstJoint + j];
				if (Joint.Kp != Drive.Kp || Joint.Kv != Drive.Kv || Joint.MaxTorque != Drive.MaxTorque)
				{
					UE_LOG(LogStreetball, Error, TEXT("LearningAgents: native swing drives require equal gains within each body"));
					return false;
				}
			}
			// Solver-level servos update every physics substep. Explicit torques held for
			// the full 20 ms policy interval are unstable for the small distal bodies.
			C->SetAngularDriveMode(EAngularDriveMode::TwistAndSwing);
			C->SetOrientationDriveTwistAndSwing(true, Body.JointCount > 1);
			C->SetAngularVelocityDriveTwistAndSwing(true, Body.JointCount > 1);
			C->SetAngularDriveAccelerationMode(false);
			C->SetAngularDriveParams(Drive.Kp * 10000, Drive.Kv * 10000, Drive.MaxTorque * 10000);
		}
		FLAComparisonBody& Parent = Bodies[Body.Parent];
		const FVector Pivot = Start + Body.ReferenceBody.GetLocation();
		const FQuat ReferenceRotation = Body.ReferenceBody.GetRotation();
		const FTransform ParentFrame(ReferenceRotation * Center * Basis, Pivot);
		const FTransform ChildFrame(ReferenceRotation * Basis, Pivot);
		// Chaos treats component 1 as the child and component 2 as its parent.
		C->SetConstrainedComponents(Body.Shape, NAME_None, Parent.Shape, NAME_None);
		const FTransform ParentGeom(Parent.Shape->GetComponentQuat(), Parent.Shape->GetComponentLocation() - Origin);
		const FTransform ChildGeom(Body.Shape->GetComponentQuat(), Body.Shape->GetComponentLocation() - Origin);
		Body.ParentConstraintFrame = ParentFrame.GetRelativeTransform(ParentGeom);
		Body.ChildConstraintFrame = ChildFrame.GetRelativeTransform(ChildGeom);
		C->SetConstraintReferenceFrame(EConstraintFrame::Frame1, Body.ChildConstraintFrame);
		C->SetConstraintReferenceFrame(EConstraintFrame::Frame2, Body.ParentConstraintFrame);
		Body.Constraint = C;
		Constraints.Add(C);
	}

	// Capture the same reference-bone offsets as the existing MuJoCo presentation mapper.
	TArray<FTransform> Bind;
	UMuJoCoBoneMapper::BindPoseComponentSpace(Mesh, Bind);
	const FReferenceSkeleton& Ref = Mesh->GetSkeletalMeshAsset()->GetRefSkeleton();
	for (int32 b = 0; b < Bodies.Num(); ++b)
	{
		const FString BodyName = Definition->BodyName(Bodies[b].ModelBody);
		if (BodyName == TEXT("head")) continue;
		const int32 Count = BodyName == TEXT("torso") ? 3 : 1;
		for (int32 k = 0; k < Count; ++k)
		{
			const FName Bone = Count == 3 ? FName(*FString::Printf(TEXT("spine_%02d"), k + 1)) : FName(*BodyName);
			const int32 Index = Ref.FindBoneIndex(Bone);
			if (Index == INDEX_NONE) return false;
			const FQuat WorldBind = Mesh->GetComponentQuat() * Bind[Index].GetRotation();
			BoneBindings.Add({Index, b, Bodies[b].ReferenceBody.GetRotation().Inverse() * WorldBind,
				Count == 3 ? float(k + 1) / 3.f : 0.f});
		}
	}
	if (!Definition->ResetToKeyframe(TEXT("stand"))) return false;
	for (FLAComparisonBody& Body : Bodies)
	{
		Body.ResetGeom = Definition->GetGeomTransformUE(M->body_geomadr[Body.ModelBody]);
	}
	Angles.SetNumZeroed(NumActions);
	Velocities.SetNumZeroed(NumActions);
	Action.SetNumZeroed(NumActions);
	PreviousAction.SetNumZeroed(NumActions);
	LastGroundContacts.Init(-1000, Bodies.Num());
	Start = Origin;
	Mesh->SetVisibility(bRender);
	ResetEpisode();
	return true;
}

FTransform ALAComparisonAgent::BodyTransform(int32 Body) const
{
	const FLAComparisonBody& B = Bodies[Body];
	return B.GeomInBody.Inverse() * B.Shape->GetComponentTransform();
}

void ALAComparisonAgent::ResetEpisode()
{
	for (const FLAComparisonBody& Body : Bodies) Body.Shape->SetSimulatePhysics(false);
	for (const FLAComparisonBody& Body : Bodies)
	{
		FTransform Transform = Body.ResetGeom;
		Transform.AddToTranslation(Start);
		Body.Shape->SetWorldTransform(Transform, false, nullptr, ETeleportType::TeleportPhysics);
		Body.Shape->SetSimulatePhysics(true);
		Body.Shape->SetMassOverrideInKg(NAME_None, Body.Shape->BodyInstance.GetMassOverride(), true);
		Body.Shape->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Body.Shape->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
		Body.Shape->SetPhysicsMaxAngularVelocityInRadians(30);
		Body.Shape->WakeAllRigidBodies();
	}
	for (FLAComparisonBody& Body : Bodies)
	{
		if (!Body.Constraint) continue;
		// InitComponentConstraint recomputes frames from the component origin. Restore the
		// imported anatomical pivots after recreating bodies; otherwise resets collapse the rig.
		Body.Constraint->InitComponentConstraint();
		Body.Constraint->SetConstraintReferenceFrame(EConstraintFrame::Frame1, Body.ChildConstraintFrame);
		Body.Constraint->SetConstraintReferenceFrame(EConstraintFrame::Frame2, Body.ParentConstraintFrame);
	}
	for (int32 j = 0; j < Joints.Num(); ++j) Angles[j] = Joints[j].Nominal;
	for (int32 j = 0; j < NumActions; ++j) { Action[j] = 0; PreviousAction[j] = 0; Velocities[j] = 0; }
	for (int32 Side = 0; Side < 2; ++Side) InitialFeet[Side] = Bodies[Feet[Side]].Shape->GetComponentLocation();
	for (float& Time : LastGroundContacts) Time = -1000;
	LastPosition = BodyTransform(Pelvis).GetLocation();
	EpisodeTime = 0; EpisodeReturn = 0; Distance = 0; PeakFootDrift = 0;
	EpisodeSteps = 0; FootContactSteps = 0; ActionRate = 0; PosePenalty = 0; TorquePenalty = 0; GroundContactTime = 0;
	bFinite = true;
	Act(Action);
	UpdateVisuals();
}

void ALAComparisonAgent::OnBodyHit(UPrimitiveComponent* Component, AActor* OtherActor, UPrimitiveComponent* OtherComponent,
	FVector NormalImpulse, const FHitResult& Hit)
{
	if (!OtherComponent || OtherComponent->GetCollisionObjectType() != ECC_WorldStatic) return;
	for (int32 b = 0; b < Bodies.Num(); ++b)
		if (Bodies[b].Shape == Component) LastGroundContacts[b] = GetWorld()->GetTimeSeconds();
}

void ALAComparisonAgent::Measure()
{
	for (const FLAComparisonBody& Body : Bodies)
	{
		if (Body.Parent == INDEX_NONE || !Body.JointCount) continue;
		const FQuat Relative = BodyTransform(Body.Parent).GetRotation().Inverse() * BodyTransform(&Body - Bodies.GetData()).GetRotation();
		float Old[3] = {};
		for (int32 j = 0; j < Body.JointCount; ++j) Old[j] = Angles[Body.FirstJoint + j];
		// Coordinate-descent inversion of the XML's ordered hinge rotations.
		for (int32 Iter = 0; Iter < 8; ++Iter)
		{
			for (int32 j = 0; j < Body.JointCount; ++j)
			{
				const int32 Index = Body.FirstJoint + j;
				FQuat Error = Relative * JointRotation(Joints, Angles, Body).Inverse();
				if (Error.W < 0) Error = Error * -1;
				const FVector Axis = JointRotation(Joints, Angles, Body, j).RotateVector(Joints[Index].Axis);
				const float Delta = float(2.0 * FVector::DotProduct(FVector(Error.X, Error.Y, Error.Z), Axis));
				Angles[Index] += Delta;
			}
		}
		for (int32 j = 0; j < Body.JointCount; ++j)
		{
			const int32 Index = Body.FirstJoint + j;
			Velocities[Index] = FMath::FindDeltaAngleRadians(Old[j], Angles[Index]) / ControlDt;
			bFinite &= FMath::IsFinite(Angles[Index]) && FMath::IsFinite(Velocities[Index]);
		}
	}
	const FVector Position = BodyTransform(Pelvis).GetLocation();
	for (const FLAComparisonBody& Body : Bodies)
		bFinite &= !Body.Shape->GetComponentTransform().ContainsNaN()
			&& !Body.Shape->GetPhysicsLinearVelocity().ContainsNaN()
			&& !Body.Shape->GetPhysicsAngularVelocityInRadians().ContainsNaN();
	Distance += FVector::Dist2D(Position, LastPosition) / 100;
	LastPosition = Position;
	PeakFootDrift = FMath::Max(PeakFootDrift, FootDrift());
	bool bNonFootContact = false;
	for (int32 b = 0; b < Bodies.Num(); ++b)
	{
		if (b == Feet[0] || b == Feet[1] || b == Hands[0] || b == Hands[1]) continue;
		bNonFootContact |= GetWorld()->GetTimeSeconds() - LastGroundContacts[b] <= 0.04f;
	}
	GroundContactTime = bNonFootContact ? GroundContactTime + ControlDt : 0;
	if (GetWorld()->GetTimeSeconds() - LastGroundContacts[Feet[0]] <= 0.04f
		|| GetWorld()->GetTimeSeconds() - LastGroundContacts[Feet[1]] <= 0.04f) ++FootContactSteps;
	EpisodeTime += ControlDt;
	++EpisodeSteps;
	EpisodeReturn += Reward();
}

void ALAComparisonAgent::Act(TConstArrayView<float> Values)
{
	if (Values.Num() != NumActions) { Comparison->Fail(TEXT("Action shape is not 27")); return; }
	ActionRate = 0; PosePenalty = 0; TorquePenalty = 0;
	for (const FLAComparisonBody& Body : Bodies)
	{
		if (Body.Parent == INDEX_NONE) continue;
		FQuat TargetRotation = FQuat::Identity;
		for (int32 j = 0; j < Body.JointCount; ++j)
		{
			const int32 JointIndex = Body.FirstJoint + j;
			const FLAComparisonJoint& Joint = Joints[JointIndex];
			const int32 a = Joint.LocalIndex;
			if (!FMath::IsFinite(Values[a])) { Comparison->Fail(TEXT("Non-finite action")); return; }
			PreviousAction[a] = Action[a];
			Action[a] = FMath::Clamp(Values[a], -1.f, 1.f);
			ActionRate += FMath::Square(Action[a] - PreviousAction[a]);
			PosePenalty += FMath::Square(Angles[JointIndex] - Joint.Nominal);
			const float Target = FMath::Clamp(Joint.Nominal + Action[a] * 0.5f * (Joint.High - Joint.Low), Joint.Low, Joint.High);
			const float Nm = FMath::Clamp(Joint.Kp * (Target - Angles[JointIndex]) - Joint.Kv * Velocities[JointIndex],
				-Joint.MaxTorque, Joint.MaxTorque);
			TorquePenalty += Nm * Nm;
			TargetRotation = TargetRotation * FQuat(Joint.Axis, Target);
		}
		if (Body.JointCount)
		{
			const FQuat ConstraintTarget = Body.ConstraintBasis.Inverse()
				* Body.ConstraintCenter.Inverse() * TargetRotation * Body.ConstraintBasis;
			Body.Constraint->SetAngularOrientationTarget(ConstraintTarget.Rotator());
		}
	}
}

float ALAComparisonAgent::FootDrift() const
{
	return float(FMath::Max(FVector::Dist2D(Bodies[Feet[0]].Shape->GetComponentLocation(), InitialFeet[0]),
		FVector::Dist2D(Bodies[Feet[1]].Shape->GetComponentLocation(), InitialFeet[1])) / 100);
}

bool ALAComparisonAgent::Fallen() const
{
	return !bFinite || BodyTransform(Pelvis).GetLocation().Z < 55 || GroundContactTime > 0.2f;
}

bool ALAComparisonAgent::OutOfBounds() const
{
	return FVector::Dist2D(BodyTransform(Pelvis).GetLocation(), Start) > 2000;
}

float ALAComparisonAgent::Reward() const
{
	const FTransform Root = BodyTransform(Pelvis);
	const float Upright = float(FMath::Square(FMath::Clamp(Root.GetRotation().GetUpVector().Z, 0.0, 1.0)));
	const float Height = FMath::Exp(-FMath::Square((float(Root.GetLocation().Z / 100) - 0.94f) / 0.1f));
	const float Speed = float(Bodies[Pelvis].Shape->GetPhysicsLinearVelocity().X / 100);
	const float Sway = float(FVector::Dist2D(Root.GetLocation(), Start + FVector(0, 0, 94)) / 100);
	const float TaskReward = TargetSpeed == 0 ? 0.5f * FMath::Exp(-FMath::Square(Sway / 0.05f)) - 2 * FootDrift()
		: FMath::Exp(-FMath::Square((Speed - TargetSpeed) / 0.5f));
	float JointVelocityPenalty = 0;
	for (float V : Velocities) JointVelocityPenalty += V * V;
	return Upright + 0.5f * Height + TaskReward + 0.2f
		- 0.05f * ActionRate - 0.002f * JointVelocityPenalty - 0.1f * PosePenalty - 1e-5f * TorquePenalty;
}

void ALAComparisonAgent::Observe(TArray<float>& Out) const
{
	Out.SetNumZeroed(NumObservations);
	const FTransform Root = BodyTransform(Pelvis);
	const FQuat Rotation = Root.GetRotation();
	const FVector Gravity = PolarToSim(Rotation.UnrotateVector(FVector(0, 0, -1)));
	const FVector Velocity = PolarToSim(Rotation.UnrotateVector(Bodies[Pelvis].Shape->GetPhysicsLinearVelocity() / 100));
	const FVector Angular = AxialToSim(Rotation.UnrotateVector(Bodies[Pelvis].Shape->GetPhysicsAngularVelocityInRadians()));
	for (int32 i = 0; i < 3; ++i) { Out[i] = float(Gravity[i]); Out[3 + i] = float(Velocity[i]); Out[6 + i] = 0.25f * float(Angular[i]); }
	for (int32 j = 0; j < NumActions; ++j)
	{
		const int32 a = Joints[j].LocalIndex;
		Out[9 + a] = Angles[j] - Joints[j].Nominal;
		Out[36 + a] = 0.1f * Velocities[j];
		Out[63 + a] = Action[a];
	}
	// Ball/task slots stay in place, but no basketball task is trained in this comparison.
	const FVector Ball = Start + FVector(300, 0, 12.05f);
	const FQuat Heading = FRotator(0, Rotation.Rotator().Yaw, 0).Quaternion();
	const FVector BallRelative = PolarToSim(Heading.UnrotateVector((Ball - Root.GetLocation()) / 100));
	const FVector BallVelocity = PolarToSim(Heading.UnrotateVector(-Bodies[Pelvis].Shape->GetPhysicsLinearVelocity() / 100));
	for (int32 i = 0; i < 3; ++i) { Out[90 + i] = float(BallRelative[i]); Out[93 + i] = 0.5f * float(BallVelocity[i]); }
	for (int32 Side = 0; Side < 2; ++Side)
	{
		Out[97 + Side] = float(FVector::Distance(Ball, Bodies[Hands[Side]].Shape->GetComponentLocation()) / 100);
		Out[99 + Side] = GetWorld()->GetTimeSeconds() - LastGroundContacts[Feet[Side]] <= 0.04f ? 1.f : 0.f;
	}
	Out[101] = float(Root.GetLocation().Z / 100);
	Out[107] = TargetSpeed;
}

void ALAComparisonAgent::UpdateVisuals()
{
	if (!Mesh->IsVisible()) return;
	UStreetballAnimInstance* Anim = Cast<UStreetballAnimInstance>(Mesh->GetAnimInstance());
	if (!Anim) return;
	FStreetballBoneTargets Targets;
	Targets.bValid = true;
	const FQuat ComponentInverse = Mesh->GetComponentQuat().Inverse();
	for (const FBoneBinding& Binding : BoneBindings)
	{
		FQuat Rotation = BodyTransform(Binding.Body).GetRotation();
		if (Binding.SpineFraction > 0)
		{
			const FQuat Root = BodyTransform(Pelvis).GetRotation();
			Rotation = Root * FQuat::Slerp(FQuat::Identity, Root.Inverse() * Rotation, Binding.SpineFraction);
		}
		Targets.Rotations.Add(Binding.Bone, ComponentInverse * Rotation * Binding.Offset);
		if (Binding.Body == Pelvis)
			Targets.Positions.Add(Binding.Bone, Mesh->GetComponentTransform().InverseTransformPosition(BodyTransform(Pelvis).GetLocation()));
	}
	Anim->SetBoneTargets(Targets);
}

void ULAComparisonInteractor::SpecifyAgentObservation_Implementation(FLearningAgentsObservationSchemaElement& Out, ULearningAgentsObservationSchema* Schema)
{
	ObservationBuffer.SetNumZeroed(NumObservations);
	FLearningAgentsObservationNormalizationSettings Settings;
	Settings.NormalizationOption = ELearningAgentsNormalization::AutoPerDimension;
	Out = ULearningAgentsObservations::SpecifyContinuousObservation(Schema, NumObservations, Settings);
}

void ULAComparisonInteractor::SpecifyAgentAction_Implementation(FLearningAgentsActionSchemaElement& Out, ULearningAgentsActionSchema* Schema)
{
	ActionBuffer.SetNumZeroed(NumActions);
	Out = ULearningAgentsActions::SpecifyContinuousAction(Schema, NumActions);
}

void ULAComparisonInteractor::GatherAgentObservation_Implementation(FLearningAgentsObservationObjectElement& Out, ULearningAgentsObservationObject* Object, int32 AgentId)
{
	ALAComparisonAgent* Agent = CastChecked<ALAComparisonAgent>(GetAgent(AgentId, ALAComparisonAgent::StaticClass()));
	Agent->Observe(ObservationBuffer);
	Out = ULearningAgentsObservations::MakeContinuousObservationFromArrayView(Object, ObservationBuffer);
}

void ULAComparisonInteractor::PerformAgentAction_Implementation(const ULearningAgentsActionObject* Object, const FLearningAgentsActionObjectElement& Element, int32 AgentId)
{
	ALAComparisonAgent* Agent = CastChecked<ALAComparisonAgent>(GetAgent(AgentId, ALAComparisonAgent::StaticClass()));
	if (!ULearningAgentsActions::GetContinuousActionToArrayView(ActionBuffer, Object, Element))
	{
		Agent->Comparison->Fail(TEXT("Learning Agents could not decode action"));
		return;
	}
	Agent->Act(ActionBuffer);
}

void ULAComparisonEnvironment::GatherAgentReward_Implementation(float& Out, int32 AgentId)
{
	const ALAComparisonAgent* Agent = CastChecked<ALAComparisonAgent>(GetAgent(AgentId, ALAComparisonAgent::StaticClass()));
	Out = Agent->Reward();
}

void ULAComparisonEnvironment::GatherAgentCompletion_Implementation(ELearningAgentsCompletion& Out, int32 AgentId)
{
	const ALAComparisonAgent* Agent = CastChecked<ALAComparisonAgent>(GetAgent(AgentId, ALAComparisonAgent::StaticClass()));
	Out = Agent->Fallen() || Agent->OutOfBounds() || (Agent->TargetSpeed == 0 && Agent->FootDrift() > 0.35f)
		? ELearningAgentsCompletion::Termination
		: (Agent->EpisodeTime >= Agent->Comparison->EpisodeSeconds ? ELearningAgentsCompletion::Truncation : ELearningAgentsCompletion::Running);
}

void ULAComparisonEnvironment::ResetAgentEpisode_Implementation(int32 AgentId)
{
	ALAComparisonAgent* Agent = CastChecked<ALAComparisonAgent>(GetAgent(AgentId, ALAComparisonAgent::StaticClass()));
	if (Agent->EpisodeSteps > 0) Agent->Comparison->RecordEpisode(Agent, Agent->Comparison->FinishedEpisode(Agent) ? TEXT("complete") : TEXT("buffer_reset"));
	Agent->ResetEpisode();
}

ALAComparisonWorld::ALAComparisonWorld()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("Root")));
	Manager = CreateDefaultSubobject<ULearningAgentsManager>(TEXT("LearningAgentsManager"));
}

void ALAComparisonWorld::Fail(const FString& Message)
{
	bFailed = true;
	bReady = false;
	UE_LOG(LogStreetball, Error, TEXT("LearningAgents comparison FAILED: %s"), *Message);
	FPlatformMisc::RequestExitWithStatus(false, 1);
}

void ALAComparisonWorld::BeginPlay()
{
	Super::BeginPlay();
	StartedAt = FPlatformTime::Seconds();
	bTrain = FParse::Param(FCommandLine::Get(), TEXT("LATrain"));
	int32 AgentCount = bTrain ? 16 : 1;
	FParse::Value(FCommandLine::Get(), TEXT("LAAgents="), AgentCount);
	FParse::Value(FCommandLine::Get(), TEXT("LATier="), Tier);
	FParse::Value(FCommandLine::Get(), TEXT("LASteps="), StepLimit);
	FParse::Value(FCommandLine::Get(), TEXT("LAIterations="), IterationLimit);
	FParse::Value(FCommandLine::Get(), TEXT("LAEpisodeSeconds="), EpisodeSeconds);
	FParse::Value(FCommandLine::Get(), TEXT("LAResume="), ResumeDir);
	if (AgentCount < 1 || AgentCount > 64 || Tier < 1 || Tier > 2 || StepLimit < 0 || IterationLimit < 0
		|| !FMath::IsFinite(EpisodeSeconds) || EpisodeSeconds < ControlDt || EpisodeSeconds > 60)
	{
		Fail(TEXT("Expected LAAgents=1..64, LATier=1..2, nonnegative steps/iterations, episode seconds=0.02..60"));
		return;
	}
	OutputDir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("LearningAgents"), FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S")));
	FParse::Value(FCommandLine::Get(), TEXT("LAOutput="), OutputDir);
	OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
	if (IFileManager::Get().DirectoryExists(*OutputDir) || !IFileManager::Get().MakeDirectory(*OutputDir, true))
	{
		Fail(TEXT("LAOutput must name a new directory (existing runs will not be overwritten)"));
		return;
	}
	EpisodeCsv = OutputDir / TEXT("episodes.csv");
	MetricCsv = OutputDir / TEXT("metrics.csv");
	if (!AppendCsv(TEXT("episode,tier,seconds,return,fallen,distance_m,foot_drift_m,reason,foot_contact_steps\n"), EpisodeCsv)
		|| !AppendCsv(TEXT("steps,wall_seconds,mean_reward,mean_height_m,mean_upright,episodes,falls,network_updates\n"), MetricCsv))
	{
		Fail(TEXT("Cannot create metric files")); return;
	}
	GetWorld()->GetWorldSettings()->bGlobalGravitySet = true;
	GetWorld()->GetWorldSettings()->GlobalGravityZ = -981;
	UPhysicsSettings* Physics = UPhysicsSettings::Get();
	bOldSubstepping = Physics->bSubstepping; OldSubstepDelta = Physics->MaxSubstepDeltaTime; OldSubsteps = Physics->MaxSubsteps;
	Physics->bSubstepping = true; Physics->MaxSubstepDeltaTime = 0.002f; Physics->MaxSubsteps = 10;
	bOldFixedTimeStep = FApp::UseFixedTimeStep(); OldFixedDelta = FApp::GetFixedDeltaTime();
	FApp::SetUseFixedTimeStep(true); FApp::SetFixedDeltaTime(ControlDt);
	bConfiguredPhysics = true;

	Definition = NewObject<UMuJoCoSim>(this);
	if (!Definition->LoadXml(Streetball::SceneXmlPath())) { Fail(TEXT("Cannot import frozen humanoid model")); return; }
	Manager->SetMaxAgentNum(AgentCount);
	for (int32 i = 0; i < AgentCount; ++i)
	{
		ALAComparisonAgent* Agent = GetWorld()->SpawnActor<ALAComparisonAgent>();
		Agent->Comparison = this;
		Agent->TargetSpeed = Tier == 2 ? 1.6f : 0;
		if (!Agent->Initialize(Definition, FVector((i % 8) * 5000, (i / 8) * 5000, 0), i == 0))
		{
			Fail(TEXT("Could not construct 15-body, 27-action Chaos humanoid")); return;
		}
		Agents.Add(Agent);
		if (Manager->AddAgent(Agent) == INDEX_NONE) { Fail(TEXT("Could not register agent")); return; }
	}
	if (!SetupLearning()) return;
	Camera = GetWorld()->SpawnActor<ACameraActor>();
	Camera->GetCameraComponent()->SetFieldOfView(55);
	if (APlayerController* PC = UGameplayStatics::GetPlayerController(GetWorld(), 0)) PC->SetViewTarget(Camera);
	bReady = true;
	UE_LOG(LogStreetball, Display, TEXT("LearningAgents comparison READY: Chaos, %d agents, tier %d, obs=119 action=27, training=%d, output=%s"),
		AgentCount, Tier, bTrain, *OutputDir);
}

bool ALAComparisonWorld::SetupLearning()
{
	ULearningAgentsManager* M = Manager;
	Interactor = ULearningAgentsInteractor::MakeInteractor(M, ULAComparisonInteractor::StaticClass());
	if (!Interactor || !Interactor->IsSetup()) { Fail(TEXT("Interactor setup failed")); return false; }
	ULearningAgentsInteractor* I = Interactor;
	FLearningAgentsPolicySettings Settings;
	Settings.HiddenLayerNum = 2; Settings.HiddenLayerSize = 256;
	Settings.MemoryCell = ELearningAgentsMemoryCell::NoMemoryCell; Settings.MemoryStateSize = 0;
	Policy = ULearningAgentsPolicy::MakePolicy(M, I, ULearningAgentsPolicy::StaticClass(), TEXT("ChaosPolicy"),
		nullptr, nullptr, nullptr, true, true, true, Settings);
	if (!Policy || !Policy->IsSetup()) { Fail(TEXT("Policy setup failed")); return false; }
	ULearningAgentsPolicy* P = Policy;
	Critic = ULearningAgentsCritic::MakeCritic(M, I, P, ULearningAgentsCritic::StaticClass());
	if (!Critic || !Critic->IsSetup()) { Fail(TEXT("Critic setup failed")); return false; }
	ULearningAgentsNeuralNetwork* Networks[] = {Policy->GetEncoderNetworkAsset(), Policy->GetPolicyNetworkAsset(),
		Policy->GetDecoderNetworkAsset(), Critic->GetCriticNetworkAsset()};
	const TCHAR* Names[] = {TEXT("encoder.bin"), TEXT("policy.bin"), TEXT("decoder.bin"), TEXT("critic.bin")};
	if (!ResumeDir.IsEmpty())
	{
		FString Json;
		FString Interface, PhysicsRevision;
		double ResumeTier = 0;
		TSharedPtr<FJsonObject> Manifest;
		if (!FFileHelper::LoadFileToString(Json, *(ResumeDir / TEXT("summary.json")))
			|| !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Manifest) || !Manifest.IsValid()
			|| !Manifest->TryGetStringField(TEXT("interface"), Interface) || Interface != TEXT("chaos_la_v1")
			|| !Manifest->TryGetStringField(TEXT("physics_revision"), PhysicsRevision) || PhysicsRevision != TEXT("native_drive_v2")
			|| !Manifest->TryGetNumberField(TEXT("tier"), ResumeTier) || ResumeTier != Tier)
		{
			Fail(TEXT("Resume requires a chaos_la_v1/native_drive_v2 summary for the selected tier")); return false;
		}
		for (int32 n = 0; n < 4; ++n)
		{
			ULearningNeuralNetworkData* Data = Networks[n]->NeuralNetworkData;
			TArray<uint8> Bytes;
			ULearningNeuralNetworkData* Check = NewObject<ULearningNeuralNetworkData>(this);
			if (!FFileHelper::LoadFileToArray(Bytes, *(ResumeDir / Names[n])) || !Check->LoadFromSnapshot(Bytes)
				|| Check->GetCompatibilityHash() != Data->GetCompatibilityHash()
				|| Check->GetInputSize() != Data->GetInputSize() || Check->GetOutputSize() != Data->GetOutputSize())
			{
				Fail(FString::Printf(TEXT("Incompatible/missing snapshot %s"), Names[n])); return false;
			}
			Data->InitFrom(Check);
		}
	}
	else
	{
		UE_LOG(LogStreetball, Warning, TEXT("LearningAgents: NEW RANDOM POLICY; this is not a trained balance/walking controller."));
	}
	InitialNetworkUpdate = Policy->GetPolicyNetworkAsset()->NeuralNetworkData->GetUpdateNumber();
	Environment = ULearningAgentsTrainingEnvironment::MakeTrainingEnvironment(M, ULAComparisonEnvironment::StaticClass());
	if (!Environment || !Environment->IsSetup()) { Fail(TEXT("Environment setup failed")); return false; }
	if (bTrain)
	{
		FLearningAgentsTrainerProcessSettings Process;
		Process.TaskName = FString::Printf(TEXT("StreetballChaos_%d"), FPlatformProcess::GetCurrentProcessId());
		Process.TrainerFileName = TEXT("learning_core.train_ppo");
		FLearningAgentsSharedMemoryCommunicatorSettings Shared;
		Shared.Timeout = 120;
		const FLearningAgentsCommunicator Communicator = ULearningAgentsCommunicatorLibrary::MakeSharedMemoryTrainingProcess(Process, Shared);
		if (!Communicator.Trainer.IsValid()) { Fail(TEXT("Python training process could not start")); return false; }
		ULearningAgentsTrainingEnvironment* E = Environment;
		ULearningAgentsCritic* C = Critic;
		FLearningAgentsPPOTrainerSettings Buffer;
		Buffer.MaxEpisodeStepNum = FMath::CeilToInt(EpisodeSeconds / ControlDt);
		Buffer.MaximumRecordedEpisodesPerIteration = 256;
		Buffer.MaximumRecordedStepsPerIteration = 4096;
		Trainer = ULearningAgentsPPOTrainer::MakePPOTrainer(M, I, E, P, C, Communicator, ULearningAgentsPPOTrainer::StaticClass(),
			TEXT("ChaosPPOTrainer"), Buffer);
		if (!Trainer || !Trainer->IsSetup()) { Fail(TEXT("PPO trainer setup failed")); return false; }
		FLearningAgentsPPOTrainingSettings Training;
		Training.NumberOfIterations = IterationLimit > 0 ? IterationLimit : 1000000;
		Training.Device = ELearningAgentsTrainingDevice::CPU;
		Training.bUseTensorboard = true; Training.bSaveSnapshots = true; Training.IterationsPerSnapshot = 10;
		Training.PolicyWindowSize = 1;
		Training.bUseGradNormMaxClipping = true;
		FLearningAgentsTrainingGameSettings Game;
		Game.FixedTimeStepFrequency = 50;
		Game.bSetMaxPhysicsStepToFixedTimeStep = false;
		Trainer->BeginTraining(Training, Game, true);
		if (!Trainer->IsTraining()) { Fail(TEXT("PPO training handshake failed")); return false; }
	}
	Policy->RunInference(bTrain ? 1.f : 0.f);
	return !bFailed;
}

bool ALAComparisonWorld::FinishedEpisode(const ALAComparisonAgent* Agent) const
{
	return Agent->Fallen() || Agent->OutOfBounds() || Agent->EpisodeTime >= EpisodeSeconds
		|| (Tier == 1 && Agent->FootDrift() > 0.35f);
}

void ALAComparisonWorld::RecordEpisode(ALAComparisonAgent* Agent, const TCHAR* Reason)
{
	++EpisodeCount;
	if (Agent->Fallen()) ++FallCount;
	const TCHAR* EndReason = Agent->Fallen() ? TEXT("fall")
		: Agent->OutOfBounds() ? TEXT("out_of_bounds")
		: Tier == 1 && Agent->FootDrift() > 0.35f ? TEXT("foot_drift")
		: Agent->EpisodeTime >= EpisodeSeconds ? TEXT("time_limit") : Reason;
	if (!AppendCsv(FString::Printf(TEXT("%d,%d,%.3f,%.6f,%d,%.4f,%.4f,%s,%d\n"), EpisodeCount, Tier,
		Agent->EpisodeTime, Agent->EpisodeReturn, Agent->Fallen(), Agent->Distance, Agent->PeakFootDrift, EndReason, Agent->FootContactSteps), EpisodeCsv))
		Fail(TEXT("Cannot append episode metrics"));
}

void ALAComparisonWorld::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bReady || bFinished) return;
	if (bFirstTick) { bFirstTick = false; return; }
	if (FMath::Abs(DeltaSeconds - ControlDt) > 0.001f) { Fail(TEXT("Comparison requires a fixed 50 Hz control step")); return; }
	for (ALAComparisonAgent* Agent : Agents)
	{
		Agent->Measure();
		if (!Agent->bFinite) { Fail(TEXT("Non-finite physics state")); return; }
	}
	TotalSteps += Agents.Num();
	if (bTrain)
	{
		Environment->GatherRewards();
		Environment->GatherCompletions();
		Trainer->ProcessExperience();
		if (Trainer->HasTrainingFailed()) { Fail(TEXT("PPO training failed; see Learning Agents log")); return; }
	}
	else
	{
		for (int32 i = 0; i < Agents.Num(); ++i)
		{
			if (FinishedEpisode(Agents[i]))
			{
				RecordEpisode(Agents[i], TEXT("complete"));
				Agents[i]->ResetEpisode();
				Manager->ResetAgent(i);
			}
		}
	}
	if (TotalSteps % (50 * Agents.Num()) == 0)
	{
		double Reward = 0, Height = 0, Upright = 0;
		for (const ALAComparisonAgent* Agent : Agents)
		{
			Reward += Agent->Reward();
			Height += Agent->BodyTransform(Agent->Pelvis).GetLocation().Z / 100;
			Upright += Agent->BodyTransform(Agent->Pelvis).GetRotation().GetUpVector().Z;
		}
		const int32 Updates = Policy->GetPolicyNetworkAsset()->NeuralNetworkData->GetUpdateNumber() - InitialNetworkUpdate;
		if (!AppendCsv(FString::Printf(TEXT("%d,%.4f,%.6f,%.5f,%.5f,%d,%d,%d\n"), TotalSteps, FPlatformTime::Seconds() - StartedAt,
			Reward / Agents.Num(), Height / Agents.Num(), Upright / Agents.Num(), EpisodeCount, FallCount, Updates), MetricCsv))
		{
			Fail(TEXT("Cannot append training metrics")); return;
		}
		if (TotalSteps % (500 * Agents.Num()) == 0 && (!SaveNetworks() || !SaveSummary()))
		{
			Fail(TEXT("Cannot save periodic checkpoint")); return;
		}
	}
	const bool bTrainingEnded = bTrain && !Trainer->IsTraining();
	if ((StepLimit > 0 && TotalSteps >= StepLimit) || bTrainingEnded)
	{
		if (Trainer && Trainer->IsTraining()) Trainer->EndTraining();
		for (ALAComparisonAgent* Agent : Agents)
			if (Agent->EpisodeSteps > 0) RecordEpisode(Agent, TEXT("run_end"));
		if (bFailed || !SaveNetworks() || !SaveSummary()) { Fail(TEXT("Cannot finalize comparison run")); return; }
		bFinished = true;
		UE_LOG(LogStreetball, Display, TEXT("LearningAgents comparison COMPLETE: %d steps, %d episodes, %d falls"), TotalSteps, EpisodeCount, FallCount);
		FPlatformMisc::RequestExitWithStatus(false, 0);
		return;
	}
	Policy->RunInference(bTrain ? 1.f : 0.f);
	for (ALAComparisonAgent* Agent : Agents) Agent->UpdateVisuals();
	const FVector Focus = Agents[0]->BodyTransform(Agents[0]->Pelvis).GetLocation();
	const FVector Location = Focus + FVector(240, 380, 130);
	Camera->SetActorLocationAndRotation(Location, (Focus - Location).Rotation());
}

bool ALAComparisonWorld::SaveNetworks()
{
	ULearningAgentsNeuralNetwork* Networks[] = {Policy->GetEncoderNetworkAsset(), Policy->GetPolicyNetworkAsset(),
		Policy->GetDecoderNetworkAsset(), Critic->GetCriticNetworkAsset()};
	const TCHAR* Names[] = {TEXT("encoder.bin"), TEXT("policy.bin"), TEXT("decoder.bin"), TEXT("critic.bin")};
	for (int32 n = 0; n < 4; ++n)
	{
		TArray<uint8> Bytes;
		Bytes.SetNumUninitialized(Networks[n]->NeuralNetworkData->GetSnapshotByteNum());
		Networks[n]->NeuralNetworkData->SaveToSnapshot(Bytes);
		const FString Path = OutputDir / Names[n];
		if (!FFileHelper::SaveArrayToFile(Bytes, *(Path + TEXT(".tmp")))
			|| !IFileManager::Get().Move(*Path, *(Path + TEXT(".tmp")), true)) return false;
	}
	return true;
}

bool ALAComparisonWorld::SaveSummary()
{
	const TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
	Summary->SetStringField(TEXT("interface"), TEXT("chaos_la_v1"));
	Summary->SetStringField(TEXT("physics"), TEXT("Chaos"));
	Summary->SetStringField(TEXT("physics_revision"), TEXT("native_drive_v2"));
	Summary->SetStringField(TEXT("trainer"), TEXT("Unreal Learning Agents PPO"));
	Summary->SetStringField(TEXT("status"), bFailed ? TEXT("failed") : TEXT("experimental_not_production"));
	Summary->SetBoolField(TEXT("training"), bTrain);
	Summary->SetNumberField(TEXT("tier"), Tier);
	Summary->SetNumberField(TEXT("agents"), Agents.Num());
	Summary->SetNumberField(TEXT("steps"), TotalSteps);
	Summary->SetNumberField(TEXT("episodes"), EpisodeCount);
	Summary->SetNumberField(TEXT("falls"), FallCount);
	Summary->SetNumberField(TEXT("control_hz"), 50);
	Summary->SetNumberField(TEXT("physics_substep_seconds"), 0.002);
	Summary->SetNumberField(TEXT("wall_seconds"), FPlatformTime::Seconds() - StartedAt);
	Summary->SetNumberField(TEXT("network_updates"), Policy->GetPolicyNetworkAsset()->NeuralNetworkData->GetUpdateNumber() - InitialNetworkUpdate);
	return WriteJson(Summary, OutputDir / TEXT("summary.json"));
}

void ALAComparisonWorld::EndPlay(const EEndPlayReason::Type Reason)
{
	if (Trainer && Trainer->IsTraining()) Trainer->EndTraining();
	if (bReady && !bFinished && !bFailed)
	{
		if (!SaveNetworks() || !SaveSummary()) UE_LOG(LogStreetball, Error, TEXT("LearningAgents: could not save on exit"));
	}
	if (bConfiguredPhysics)
	{
		UPhysicsSettings* Physics = UPhysicsSettings::Get();
		Physics->bSubstepping = bOldSubstepping; Physics->MaxSubstepDeltaTime = OldSubstepDelta; Physics->MaxSubsteps = OldSubsteps;
		FApp::SetUseFixedTimeStep(bOldFixedTimeStep); FApp::SetFixedDeltaTime(OldFixedDelta);
	}
	Super::EndPlay(Reason);
}

FString ALAComparisonWorld::StatusText() const
{
	return FString::Printf(TEXT("UNREAL LEARNING AGENTS + CHAOS\nTier %d: %s | %s\n%d agents | %d steps | %d episodes | %d falls\n%s\nMuJoCo scene and production policies are unchanged."),
		Tier, Tier == 1 ? TEXT("Balance") : TEXT("Commanded walking"),
		bTrain ? TEXT("TRAINING") : TEXT("PREVIEW"),
		Agents.Num(), TotalSteps, EpisodeCount, FallCount,
		ResumeDir.IsEmpty() ? TEXT("UNTRAINED RANDOM POLICY - not a learned skill") : TEXT("Experimental candidate checkpoint - not production"));
}

ALAComparisonGameMode::ALAComparisonGameMode()
{
	DefaultPawnClass = ASpectatorPawn::StaticClass();
	HUDClass = ALAComparisonHUD::StaticClass();
	bStartPlayersAsSpectators = true;
}

void ALAComparisonHUD::DrawHUD()
{
	Super::DrawHUD();
	if (!Canvas) return;
	for (TActorIterator<ALAComparisonWorld> It(GetWorld()); It; ++It)
	{
		DrawRect(FLinearColor(0, 0, 0, 0.7f), 12, 12, 700, 160);
		DrawText(It->StatusText(), FLinearColor(0.4f, 0.9f, 1), 24, 24);
		break;
	}
	DrawText(FString::Printf(TEXT("build %s"), *UStreetballHUDWidget::BuildStampYYMMDD()),
		FLinearColor::White, Canvas->SizeX - 115.f, Canvas->SizeY - 30.f);
}
