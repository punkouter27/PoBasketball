#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ObsBuilder.h"
#include "CourtAudio.h"
#include "StreetballDirector.h"
#include "StreetballWorld.generated.h"

class UMuJoCoSim;
class USimClock;
class UMuJoCoBoneMapper;
class UPolicyRunner;
class UStreetballTracker;
class ABroadcastCamera;
class UStreetballHUDWidget;
class USkeletalMeshComponent;
class UStaticMeshComponent;
class USceneComponent;

/** The athlete: a skeletal mesh whose bones are written by UMuJoCoBoneMapper. Chaos off. */
UCLASS()
class STREETBALLGYM_API AStreetballCharacter : public AActor
{
	GENERATED_BODY()
public:
	AStreetballCharacter();
	UPROPERTY(VisibleAnywhere) TObjectPtr<USceneComponent> Root;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USkeletalMeshComponent> Mesh;
};

/** One visual proxy for a sim geom (static shapes for the court, the ball, and optional debug geoms). */
UCLASS()
class STREETBALLGYM_API AStreetballGeomActor : public AActor
{
	GENERATED_BODY()
public:
	AStreetballGeomActor();
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStaticMeshComponent> Mesh;
	int32 GeomId = INDEX_NONE;
	int32 BodyId = INDEX_NONE;
	bool bDynamic = false;
	FTransform GeomInBody = FTransform::Identity;
	FVector MeshScale = FVector::OneVector;
	FQuat MeshRot = FQuat::Identity;
};

/**
 * Plan B3/B8/B9/B10: owns the sim, the clock, the tracker, the director, the camera, the audio
 * and every visual actor. All actors are created in BeginPlay; nothing is spawned or destroyed
 * afterwards. Resets write qpos/qvel; they never respawn.
 */
UCLASS()
class STREETBALLGYM_API AStreetballWorld : public AActor
{
	GENERATED_BODY()

public:
	AStreetballWorld();

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	UPROPERTY(EditAnywhere, Category = "Streetball") FString KeyframeName = TEXT("stand");
	UPROPERTY(EditAnywhere, Category = "Streetball") bool bShowHumanoidGeoms = false;
	/** Directory with <level>.onnx policies; relative paths resolve against Content/Sim. */
	UPROPERTY(EditAnywhere, Category = "Streetball") FString PolicyDir = TEXT("policies");
	UPROPERTY(EditAnywhere, Category = "Streetball") FString FallbackPolicy = TEXT("policies/dummy_policy.onnx");
	UPROPERTY(EditAnywhere, Category = "Streetball") FString AudioBankPath = TEXT("/Game/Audio/DA_CourtAudioBank.DA_CourtAudioBank");
	UPROPERTY(EditAnywhere, Category = "Streetball") int32 DirectorSeed = 7;

	UMuJoCoSim* GetSim() const { return Sim; }
	USimClock* GetClock() const { return Clock; }
	UMuJoCoBoneMapper* GetBoneMapper() const { return BoneMapper; }
	AStreetballCharacter* GetCharacter() const { return Character; }
	UStreetballTracker* GetTracker() const { return Tracker; }
	UStreetballDirector* GetDirector() const { return Director; }
	ABroadcastCamera* GetCamera() const { return Camera; }
	UStreetballHUDWidget* GetHUD() const { return HUD; }
	const TMap<FString, TObjectPtr<UPolicyRunner>>& GetPolicies() const { return Policies; }
	const TArray<FString>& GetRealPolicyNames() const { return RealPolicies; }
	const TArray<FCourtAudioEvent>& GetRecentAudioEvents() const { return RecentEvents; }
	int32 GetAudioPlayedCount() const { return AudioPlayer.PlayedCount; }
	const FStreetballDirectorOutput& GetLastDirectorOutput() const { return DirOut; }
	int32 GetResetCount() const { return ResetCount; }

	/** Builds the whole world against an already-loaded sim. Exposed so tests can drive it without a level. */
	bool Setup(UWorld* InWorld);

	/** Apply a director reset spec (keyframe + optional root/ball placement). Public for tests. */
	void ApplyReset(const FStreetballResetSpec& Spec);

	/** Run one control step by hand (tests). */
	void StepControl();

private:
	void OnControlStep(UMuJoCoSim* InSim);
	void OnPhysicsStep(UMuJoCoSim* InSim);
	void UpdateVisuals();
	void UpdateCameraAndHUD(float Dt);
	UPolicyRunner* LoadPolicy(const FString& LevelName);
	static bool EnginePrimitiveForGeom(int32 GeomType, const FVector& SizeM, FString& OutMeshPath, FVector& OutScale);

	UPROPERTY() TObjectPtr<UMuJoCoSim> Sim;
	UPROPERTY() TObjectPtr<USimClock> Clock;
	UPROPERTY() TObjectPtr<UMuJoCoBoneMapper> BoneMapper;
	UPROPERTY() TObjectPtr<UStreetballTracker> Tracker;
	UPROPERTY() TObjectPtr<UStreetballDirector> Director;
	UPROPERTY() TMap<FString, TObjectPtr<UPolicyRunner>> Policies;
	UPROPERTY() TObjectPtr<UPolicyRunner> Fallback;
	UPROPERTY() TObjectPtr<AStreetballCharacter> Character;
	UPROPERTY() TArray<TObjectPtr<AStreetballGeomActor>> GeomActors;
	UPROPERTY() TObjectPtr<AStreetballGeomActor> BallActor;
	UPROPERTY() TObjectPtr<ABroadcastCamera> Camera;
	UPROPERTY() TObjectPtr<UCourtAudioBank> AudioBank;
	UPROPERTY() TObjectPtr<UStreetballHUDWidget> HUD;

	FObsBuilder ObsBuilder;
	FContactAudioProcessor AudioProc;
	FCourtAudioPlayer AudioPlayer;
	TArray<FCourtAudioEvent> PendingEvents;
	TArray<FCourtAudioEvent> RecentEvents;
	TArray<FString> RealPolicies;
	FStreetballDirectorOutput DirOut;

	TArray<float> HoldCtrl;
	TArray<float> PrevAction;
	TArray<float> Obs;
	TArray<float> Action;
	int32 PelvisBody = INDEX_NONE;
	int32 BallBody = INDEX_NONE;
	int32 ResetCount = 0;
	bool bReady = false;
};
