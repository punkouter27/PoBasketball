#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/HUD.h"
#include "LearningAgentsInteractor.h"
#include "LearningAgentsTrainingEnvironment.h"
#include "LearningAgentsComparison.generated.h"

class UMuJoCoSim;
class UShapeComponent;
class USkeletalMeshComponent;
class UPhysicsConstraintComponent;
class ULearningAgentsManager;
class ULearningAgentsPolicy;
class ULearningAgentsCritic;
class ULearningAgentsPPOTrainer;
class ACameraActor;
class ALAComparisonWorld;

struct FLAComparisonBody
{
	int32 ModelBody = INDEX_NONE;
	int32 Parent = INDEX_NONE;
	int32 FirstJoint = 0;
	int32 JointCount = 0;
	UShapeComponent* Shape = nullptr;
	UPhysicsConstraintComponent* Constraint = nullptr;
	FTransform GeomInBody;
	FTransform ReferenceBody;
	FTransform ResetGeom;
	FTransform ParentConstraintFrame;
	FTransform ChildConstraintFrame;
	FQuat ConstraintBasis = FQuat::Identity;
	FQuat ConstraintCenter = FQuat::Identity;
};

struct FLAComparisonJoint
{
	FVector Axis = FVector::ZeroVector;
	float Nominal = 0;
	float Low = 0;
	float High = 0;
	float Kp = 0;
	float Kv = 0;
	float MaxTorque = 0;
	int32 Body = INDEX_NONE;
	int32 LocalIndex = 0;
};

UCLASS()
class STREETBALLGYM_API ALAComparisonAgent : public AActor
{
	GENERATED_BODY()
public:
	ALAComparisonAgent();
	bool Initialize(UMuJoCoSim* Definition, const FVector& Origin, bool bRender);
	void ResetEpisode();
	void Measure();
	void Act(TConstArrayView<float> Values);
	void UpdateVisuals();
	FTransform BodyTransform(int32 Body) const;
	float Reward() const;
	bool Fallen() const;
	bool OutOfBounds() const;
	float FootDrift() const;
	void Observe(TArray<float>& Out) const;
	UFUNCTION() void OnBodyHit(UPrimitiveComponent* Component, AActor* OtherActor, UPrimitiveComponent* OtherComponent,
		FVector NormalImpulse, const FHitResult& Hit);

	UPROPERTY(Transient) TObjectPtr<USkeletalMeshComponent> Mesh;
	UPROPERTY(Transient) TObjectPtr<ALAComparisonWorld> Comparison;
	UPROPERTY(Transient) TArray<TObjectPtr<UShapeComponent>> Shapes;
	UPROPERTY(Transient) TArray<TObjectPtr<UPhysicsConstraintComponent>> Constraints;
	TArray<FLAComparisonBody> Bodies;
	TArray<FLAComparisonJoint> Joints;
	TArray<float> Angles, Velocities, Action, PreviousAction;
	TArray<float> LastGroundContacts;
	FVector Start = FVector::ZeroVector;
	FVector InitialFeet[2];
	int32 Pelvis = INDEX_NONE;
	int32 Feet[2] = {INDEX_NONE, INDEX_NONE};
	int32 Hands[2] = {INDEX_NONE, INDEX_NONE};
	float EpisodeTime = 0;
	float EpisodeReturn = 0;
	float Distance = 0;
	float PeakFootDrift = 0;
	float ActionRate = 0;
	float PosePenalty = 0;
	float TorquePenalty = 0;
	float GroundContactTime = 0;
	int32 EpisodeSteps = 0;
	int32 FootContactSteps = 0;
	bool bFinite = true;
	float TargetSpeed = 0;

private:
	struct FBoneBinding { int32 Bone; int32 Body; FQuat Offset; float SpineFraction = 0; };
	TArray<FBoneBinding> BoneBindings;
	FVector LastPosition = FVector::ZeroVector;
};

UCLASS()
class STREETBALLGYM_API ULAComparisonInteractor : public ULearningAgentsInteractor
{
	GENERATED_BODY()
public:
	virtual void SpecifyAgentObservation_Implementation(FLearningAgentsObservationSchemaElement& Out, ULearningAgentsObservationSchema* Schema) override;
	virtual void SpecifyAgentAction_Implementation(FLearningAgentsActionSchemaElement& Out, ULearningAgentsActionSchema* Schema) override;
	virtual void GatherAgentObservation_Implementation(FLearningAgentsObservationObjectElement& Out, ULearningAgentsObservationObject* Object, int32 AgentId) override;
	virtual void PerformAgentAction_Implementation(const ULearningAgentsActionObject* Object, const FLearningAgentsActionObjectElement& Element, int32 AgentId) override;
private:
	TArray<float> ObservationBuffer, ActionBuffer;
};

UCLASS()
class STREETBALLGYM_API ULAComparisonEnvironment : public ULearningAgentsTrainingEnvironment
{
	GENERATED_BODY()
public:
	virtual void GatherAgentReward_Implementation(float& Out, int32 AgentId) override;
	virtual void GatherAgentCompletion_Implementation(ELearningAgentsCompletion& Out, int32 AgentId) override;
	virtual void ResetAgentEpisode_Implementation(int32 AgentId) override;
};

UCLASS()
class STREETBALLGYM_API ALAComparisonWorld : public AActor
{
	GENERATED_BODY()
public:
	ALAComparisonWorld();
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	void RecordEpisode(ALAComparisonAgent* Agent, const TCHAR* Reason);
	void Fail(const FString& Message);
	bool FinishedEpisode(const ALAComparisonAgent* Agent) const;
	bool IsTrainingMode() const { return bTrain; }
	FString StatusText() const;

	UPROPERTY(Transient) TObjectPtr<ULearningAgentsManager> Manager;
	UPROPERTY(Transient) TObjectPtr<ULearningAgentsInteractor> Interactor;
	UPROPERTY(Transient) TObjectPtr<ULearningAgentsTrainingEnvironment> Environment;
	UPROPERTY(Transient) TObjectPtr<ULearningAgentsPolicy> Policy;
	UPROPERTY(Transient) TObjectPtr<ULearningAgentsCritic> Critic;
	UPROPERTY(Transient) TObjectPtr<ULearningAgentsPPOTrainer> Trainer;
	UPROPERTY(Transient) TObjectPtr<UMuJoCoSim> Definition;
	UPROPERTY(Transient) TArray<TObjectPtr<ALAComparisonAgent>> Agents;
	UPROPERTY(Transient) TObjectPtr<ACameraActor> Camera;
	float EpisodeSeconds = 60;
	int32 Tier = 1;
	int32 TotalSteps = 0;
	int32 EpisodeCount = 0;
	int32 FallCount = 0;

private:
	bool SetupLearning();
	bool SaveNetworks();
	bool SaveSummary();
	bool bTrain = false;
	bool bReady = false;
	bool bFailed = false;
	bool bFinished = false;
	bool bConfiguredPhysics = false;
	bool bFirstTick = true;
	bool bOldSubstepping = false;
	bool bOldFixedTimeStep = false;
	float OldSubstepDelta = 0;
	int32 OldSubsteps = 0;
	double OldFixedDelta = 0;
	double StartedAt = 0;
	int32 StepLimit = 0;
	int32 IterationLimit = 0;
	int32 InitialNetworkUpdate = 0;
	FString OutputDir;
	FString ResumeDir;
	FString EpisodeCsv;
	FString MetricCsv;
};

UCLASS()
class STREETBALLGYM_API ALAComparisonGameMode : public AGameModeBase
{
	GENERATED_BODY()
public:
	ALAComparisonGameMode();
};

UCLASS()
class STREETBALLGYM_API ALAComparisonHUD : public AHUD
{
	GENERATED_BODY()
public:
	virtual void DrawHUD() override;
};
