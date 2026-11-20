#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ObsBuilder.h"
#include "CourtAudio.h"
#include "StreetballDirector.h"
#include "CourtFX.h"
#include "GrandmaVoice.h"
#include "PresentationEvents.h"
#include "StreetballCrowd.h"
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
class UGroomComponent;
class UMaterialInterface;

UENUM(BlueprintType)
enum class EStreetballAppMode : uint8
{
	Watch,
	Play,
	Testbed
};

/** The athlete: a skeletal mesh whose bones are written by UMuJoCoBoneMapper. Chaos off. */
UCLASS()
class STREETBALLGYM_API AStreetballCharacter : public AActor
{
	GENERATED_BODY()
public:
	AStreetballCharacter();
	/** Main character skin (visual only; re-proportioned onto Manny's joints by Scripts/retarget_grandma_blender.py). */
	static constexpr const TCHAR* GrandmaMeshPath = TEXT("/Game/Art/Characters/Grandma/SK_Grandma.SK_Grandma");
	/** Same skin with the cardigan hem split into a Chaos Cloth section (Scripts/build_grandma_extras.py). Preferred. */
	static constexpr const TCHAR* GrandmaClothMeshPath = TEXT("/Game/Art/Characters/Grandma/SK_Grandma_Cloth.SK_Grandma_Cloth");
	static constexpr const TCHAR* GroomFlyawaysPath = TEXT("/Game/Art/Characters/Grandma/Groom/GR_Grandma_Flyaways.GR_Grandma_Flyaways");
	static constexpr const TCHAR* GroomBrowsPath = TEXT("/Game/Art/Characters/Grandma/Groom/GR_Grandma_Brows.GR_Grandma_Brows");
	/**
	 * Mesh priority: -StreetballCharacterMesh=<object path> (e.g. a MetaHuman body on the UE5 skeleton), then the cloth
	 * grandma, the plain grandma, Manny. -StreetballCharacter=Manny forces Manny. -StreetballNoCloth skips the cloth mesh.
	 * Must run before UMuJoCoBoneMapper::Initialize (offsets are captured from the bind pose). Returns the mesh in use.
	 */
	FString ApplyMainCharacterMesh();
	/** Cosmetic extras on the grandma skin: groom layers (bound to the mesh, or rigid on the head bone). */
	void AttachExtras();
	/** Face mesh whose morph targets the voice drives (the body itself for the CC grandma). */
	USkeletalMeshComponent* GetFaceMesh() const { return Mesh; }
	int32 NumGrooms() const;
	bool HasCloth() const;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USceneComponent> Root;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USkeletalMeshComponent> Mesh;
	UPROPERTY(VisibleAnywhere) TArray<TObjectPtr<UGroomComponent>> Grooms;
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
	/** shared/transition_table.json copy; relative paths resolve against Content/Sim. */
	UPROPERTY(EditAnywhere, Category = "Streetball") FString TransitionTablePath = TEXT("transition_table.json");
	UPROPERTY(EditAnywhere, Category = "Streetball") FString AudioBankPath = TEXT("/Game/Audio/DA_CourtAudioBank.DA_CourtAudioBank");
	UPROPERTY(EditAnywhere, Category = "Streetball") int32 DirectorSeed = 7;
	UPROPERTY(EditAnywhere, Category = "Presentation") FString FXBankPath = TEXT("/Game/VFX/DA_CourtFXBank.DA_CourtFXBank");
	UPROPERTY(EditAnywhere, Category = "Presentation") FString VoiceBankPath = TEXT("/Game/Audio/Voice/DA_GrandmaVoiceBank.DA_GrandmaVoiceBank");
	/** Cosmetic materials by sim geom name prefix (first match wins; longest prefixes first). Missing assets keep the MJCF colour. */
	UPROPERTY(EditAnywhere, Category = "Presentation") TMap<FString, FString> GeomMaterialOverrides;
	/** -StreetballNoPresentation turns voice/VFX/ambience off (gate replays). */
	UPROPERTY(EditAnywhere, Category = "Presentation") bool bPresentation = true;

	UMuJoCoSim* GetSim() const { return Sim; }
	USimClock* GetClock() const { return Clock; }
	UMuJoCoBoneMapper* GetBoneMapper() const { return BoneMapper; }
	AStreetballCharacter* GetCharacter() const { return Character; }
	UStreetballTracker* GetTracker() const { return Tracker; }
	UStreetballDirector* GetDirector() const { return Director; }
	ABroadcastCamera* GetCamera() const { return Camera; }
	UStreetballHUDWidget* GetHUD() const { return HUD; }
	const TMap<FName, TObjectPtr<UPolicyRunner>>& GetPolicies() const { return Policies; }
	const TArray<FString>& GetRealPolicyNames() const { return RealPolicies; }
	const TArray<FCourtAudioEvent>& GetRecentAudioEvents() const { return RecentEvents; }
	int32 GetAudioPlayedCount() const { return AudioPlayer.PlayedCount; }
	const FStreetballDirectorOutput& GetLastDirectorOutput() const { return DirOut; }
	int32 GetResetCount() const { return ResetCount; }
	const TCHAR* GetLastResetReason() const { return LastResetReason; }
	/** Observation fed to the policy at the last control step and the action it produced (tests). */
	const TArray<float>& GetLastObs() const { return Obs; }
	const TArray<float>& GetLastAction() const { return Action; }
	const TArray<float>& GetPrevAction() const { return PrevAction; }
	FName GetLastPolicyName() const { return LastPolicyName; }
	const FCourtFXPlayer& GetFXPlayer() const { return FXPlayer; }
	const FGrandmaVoicePlayer& GetVoice() const { return Voice; }
	const FCourtCrowdPlayer& GetCrowd() const { return Crowd; }
	int32 GetPresentationEventCount(EPresentationEvent E) const { return PresentationCounts[(int32)E]; }
	bool IsAmbiencePlaying() const { return AudioPlayer.IsAmbiencePlaying(); }
	int32 GetMaterialOverrideCount() const { return MaterialOverrideCount; }
	float GetExertion01() const { return Exertion01; }
	float GetLastPowerWatts() const { return LastPowerW; }

	/** Builds the whole world against an already-loaded sim. Exposed so tests can drive it without a level. */
	bool Setup(UWorld* InWorld);

	/** Apply a director reset spec (keyframe + optional root/ball placement). Public for tests. */
	void ApplyReset(const FStreetballResetSpec& Spec);

	/** Run one control step by hand (tests). */
	void StepControl();

	/** Standardized Profile B runtime controls (F1-F4 / M,C,T,P, Space, R). */
	EStreetballAppMode CycleAppMode();
	void CycleCameraMode();
	void ToggleTelemetry();
	void CyclePolicyOverride();
	void TogglePause() { bPaused = !bPaused; }
	void ResetEpisode();

	/** Play & Testbed interactive controls (#1). */
	void JumpToTier(int32 Tier);
	void CommandCourtTarget(const FVector2d& SimXY);
	void LobBallToAthlete();
	void ApplyTestbedPush(const FVector2d& DirSim, float ForceN = 120.f, float DurationS = 0.2f);
	void StepTimeScale(int32 DeltaIndex);
	float GetTimeScale() const;

	EStreetballAppMode GetAppMode() const { return AppMode; }
	bool IsPaused() const { return bPaused; }
	int32 GetNanInfCount() const { return NanInfCount; }
	float GetEpisodeReward() const { return EpisodeReward; }

private:
	void OnControlStep(UMuJoCoSim* InSim);
	void OnPhysicsStep(UMuJoCoSim* InSim);
	void UpdateVisuals();
	void UpdatePresentation(float Dt);
	void SetupPresentation();
	void UpdateCaptureSchedule();
	UMaterialInterface* MaterialOverrideFor(const FString& GeomName) const;
	void UpdateCameraAndHUD(float Dt);
	UPolicyRunner* LoadPolicy(const FString& LevelName);
	static bool EnginePrimitiveForGeom(int32 GeomType, const FVector& SizeM, FString& OutMeshPath, FVector& OutScale);

	UPROPERTY() TObjectPtr<UMuJoCoSim> Sim;
	UPROPERTY() TObjectPtr<USimClock> Clock;
	UPROPERTY() TObjectPtr<UMuJoCoBoneMapper> BoneMapper;
	UPROPERTY() TObjectPtr<UStreetballTracker> Tracker;
	UPROPERTY() TObjectPtr<UStreetballDirector> Director;
	UPROPERTY() TMap<FName, TObjectPtr<UPolicyRunner>> Policies;
	UPROPERTY() TObjectPtr<UPolicyRunner> Fallback;
	UPROPERTY() TObjectPtr<AStreetballCharacter> Character;
	/** Visual-only ground apron outside the fence (not part of the sim). */
	UPROPERTY() TObjectPtr<AStreetballGeomActor> Surroundings;
	UPROPERTY() TArray<TObjectPtr<AStreetballGeomActor>> GeomActors;
	UPROPERTY() TObjectPtr<AStreetballGeomActor> BallActor;
	UPROPERTY() TObjectPtr<ABroadcastCamera> Camera;
	UPROPERTY() TObjectPtr<UCourtAudioBank> AudioBank;
	UPROPERTY() TObjectPtr<UStreetballHUDWidget> HUD;
	UPROPERTY() TObjectPtr<UCourtFXBank> FXBank;
	UPROPERTY() TObjectPtr<UGrandmaVoiceBank> VoiceBank;
	UPROPERTY() TMap<FString, TObjectPtr<UMaterialInterface>> LoadedOverrides;

	FObsBuilder ObsBuilder;
	FContactAudioProcessor AudioProc;
	FCourtAudioPlayer AudioPlayer;
	TArray<FCourtAudioEvent> PendingEvents;
	TArray<FCourtAudioEvent> RecentEvents;
	FCourtFXPlayer FXPlayer;
	FGrandmaVoicePlayer Voice;
	FCourtCrowdPlayer Crowd;
	FPresentationEventDetector EventDetector;
	TArray<EPresentationEvent> PendingPresentation;
	int32 PresentationCounts[(int32)EPresentationEvent::Count] = {0};
	int32 MaterialOverrideCount = 0;
	float Exertion01 = 0.f;
	float LastPowerW = 0.f;
	double NextExertionSweatT = 0.0;
	FVector2d ActivePushForceSim = FVector2d::ZeroVector;
	double PushRemainingS = 0.0;
	int32 TimeScaleIdx = 2; // 0.25, 0.5, 1.0, 1.5, 2.0
	TArray<FString> RealPolicies;
	FStreetballDirectorOutput DirOut;
	FName LastPolicyName;
	// pre-sized scratch for the control step (UU_AGENT: no heap allocation in the real-time loop)
	TArray<float> CtrlBuf;
	TArray<double> QBuf, VBuf;
	int32 RootQAdr = INDEX_NONE, BallQAdr = INDEX_NONE, BallVAdr = INDEX_NONE;
	int32 UnloggedResets = 0;                    // resets applied inside the step, logged from Tick
	const TCHAR* LastResetReason = TEXT("");

	TArray<float> HoldCtrl;
	TArray<float> PrevAction;
	TArray<float> Obs;
	TArray<float> Action;
	int32 PelvisBody = INDEX_NONE;
	int32 BallBody = INDEX_NONE;
	int32 ResetCount = 0;
	bool bReady = false;
	bool bPaused = false;
	EStreetballAppMode AppMode = EStreetballAppMode::Watch;
	TArray<FName> PolicyOrder;
	int32 ForcedPolicyIndex = INDEX_NONE;
	int32 NanInfCount = 0;
	// DEBUG ONLY (-StreetballObsDump=<file>): first 150 control steps (qpos, qvel, task, flags, obs, action) as CSV.
	// Allocates; off unless the switch is given (UU: no allocation in the real-time loop in normal play).
	FString ObsDumpPath;
	FString ObsDumpBuf;
	int32 ObsDumpRows = 0;
	float EpisodeReward = 0.f;
	float SmoothedFps = 60.f;
};
