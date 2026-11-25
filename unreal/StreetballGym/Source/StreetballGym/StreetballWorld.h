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
	static constexpr const TCHAR* GrandmaMeshPath = TEXT("/Game/Project/Agents/Grandma/SK_Grandma.SK_Grandma");
	/** Same skin with the cardigan hem split into a Chaos Cloth section (Scripts/build_grandma_extras.py). Preferred. */
	static constexpr const TCHAR* GrandmaClothMeshPath = TEXT("/Game/Project/Agents/Grandma/SK_Grandma_Cloth.SK_Grandma_Cloth");
	static constexpr const TCHAR* GroomFlyawaysPath = TEXT("/Game/Project/Agents/Grandma/Groom/GR_Grandma_Flyaways.GR_Grandma_Flyaways");
	static constexpr const TCHAR* MannyMeshPath = TEXT("/Game/Project/Agents/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple");
	static constexpr const TCHAR* QuinnMeshPath = TEXT("/Game/Project/Agents/Mannequins/Meshes/SKM_Quinn_Simple.SKM_Quinn_Simple");
	static constexpr const TCHAR* GroomBrowsPath =TEXT("/Game/Project/Agents/Grandma/Groom/GR_Grandma_Brows.GR_Grandma_Brows");
	/**
	 * Mesh priority: -StreetballCharacterMesh=<object path> (e.g. a MetaHuman body on the UE5 skeleton), then the cloth
	 * grandma, the plain grandma, Manny. -StreetballCharacter=Manny forces Manny. -StreetballNoCloth skips the cloth mesh.
	 * Must run before UMuJoCoBoneMapper::Initialize (offsets are captured from the bind pose). Returns the mesh in use.
	 */
	FString ApplyMainCharacterMesh();
	/** Cosmetic extras on the grandma skin: groom layers (bound to the mesh, or rigid on the head bone). */
	void AttachExtras();
	/**
	 * Local-only MetaHuman grandma (2026-11-24; git-ignored, built by Scripts/build_grandma_metahuman.py +
	 * import_grandma_metahuman.py): Content/Art/Exports/GrandmaMH/parts.json lists the re-proportioned body (on Manny's
	 * joints, so the bone mapper drives it like the CC grandma), its outfit (leader pose), the native MetaHuman face
	 * (ABP_Face copies the pose from its attach parent, the body) and the grooms bound to the face. Missing file or assets
	 * = the CC grandma as before. -StreetballNoMetaHuman skips it.
	 */
	/** MetaHuman skins, each from its own parts.json (2026-11-24): 0 = the original grandma's face on her own clothed
	 *  body, 1 = the Grace-preset grandma. The parameterless overload returns the first slot present. */
	static constexpr int32 NumMetaHumanSlots = 2;
	static bool LoadMetaHumanParts(int32 Slot, TSharedPtr<class FJsonObject>& Out);
	static bool LoadMetaHumanParts(TSharedPtr<class FJsonObject>& Out);
	static const TCHAR* MetaHumanSlotLabel(int32 Slot);
	void AttachMetaHuman(const TSharedPtr<class FJsonObject>& Parts, int32 Slot);
	/** Slot of the active skin, INDEX_NONE when the active skin is not a MetaHuman. */
	int32 ActiveMetaHumanSlot() const;
	bool IsMetaHuman() const { return ActiveMetaHumanSlot() != INDEX_NONE && FaceMesh != nullptr; }
	/**
	 * Live humanoid switch (Dribble Lab, 2026-11-24). Every skin is loaded once at startup (BuildSkins, from
	 * ApplyMainCharacterMesh); SetSkin only swaps the mesh asset on the one body component and toggles the extras'
	 * visibility, so nothing is spawned at runtime. All skins share Manny's joints; the caller re-initialises the bone
	 * mapper (bind offsets differ per skin). Visual only: the MuJoCo body and the policies do not change.
	 */
	int32 NumSkins() const { return SkinMeshes.Num(); }
	int32 GetActiveSkin() const { return ActiveSkin; }
	const TArray<FString>& GetSkinNames() const { return SkinNames; }
	bool SetSkin(int32 Index);
	/**
	 * Face mood (2026-11-24): Smile01 / Frown01 in [0, 1]. On the MetaHuman skin the weights become CTRL_expressions_*
	 * curves read from Epic's ARKit mapping pose asset (MouthSmile, CheekSquint, MouthFrown, BrowDown, ...), emitted by
	 * the body anim instance; ABP_Face copies them to the face and RigLogic shapes it. The CC grandma is handled by
	 * FGrandmaVoicePlayer (morph targets). Other skins ignore it. Game thread, no allocation.
	 */
	void SetFaceMood(float Smile01, float Frown01);
	int32 NumFaceCurves() const { return FaceCurveNames.Num(); }
	/** Head bone in UE world space (face camera); falls back to the actor location + 1.6 m. */
	FVector GetHeadLocationUE() const;
	/** Unit vector the face points along (UE world), from the head bone's current rotation. */
	FVector GetFaceDirectionUE() const;
	static constexpr const TCHAR* ARKitMappingPath = TEXT("/Game/Project/Agents/GrandmaMH/Build/Common/Face/ARKit/PA_MetaHuman_ARKit_Mapping.PA_MetaHuman_ARKit_Mapping");
	static constexpr uint8 SkinKindPlain = 0;
	static constexpr uint8 SkinKindMetaHuman = 1;
	static constexpr uint8 SkinKindGrandma = 2;
	/** Face mesh whose morph targets the voice drives (the body itself for the CC grandma). */
	USkeletalMeshComponent* GetFaceMesh() const { return Mesh; }
	int32 NumGrooms() const;
	bool HasCloth() const;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USceneComponent> Root;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USkeletalMeshComponent> Mesh;
	UPROPERTY(VisibleAnywhere) TArray<TObjectPtr<UGroomComponent>> Grooms;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USkeletalMeshComponent> FaceMesh;
	UPROPERTY(VisibleAnywhere) TObjectPtr<USkeletalMeshComponent> OutfitMesh;
	UPROPERTY() TArray<TObjectPtr<USkeletalMesh>> SkinMeshes;
	/** Per MetaHuman slot (FaceMesh / OutfitMesh point at the active one). */
	UPROPERTY() TArray<TObjectPtr<USkeletalMeshComponent>> MHFaces;
	UPROPERTY() TArray<TObjectPtr<USkeletalMeshComponent>> MHOutfits;
private:
	void BuildSkins();
	void ApplySkinExtrasVisibility();
	void AttachGrandmaGrooms(const USkeletalMesh* GrandmaMesh, bool bForceRigid);
	void BuildFaceRig();
	TArray<FName> FaceCurveNames;
	TArray<float> FaceSmileW, FaceFrownW, FaceCurveValues;
	mutable const USkeletalMesh* FaceDirMesh = nullptr;   // cache key for FaceDirInHead
	mutable FVector FaceDirInHead = FVector(0.f, 1.f, 0.f);
	TArray<FString> SkinNames;
	TArray<uint8> SkinKinds;
	TArray<int32> SkinMHSlot;   // per skin: MetaHuman slot or INDEX_NONE
	int32 ActiveSkin = INDEX_NONE;
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
	/** Directory with <level>.onnx policies; relative paths resolve against Content/Project/RL_Policies. */
	UPROPERTY(EditAnywhere, Category = "Streetball") FString PolicyDir = TEXT("policies");
	UPROPERTY(EditAnywhere, Category = "Streetball") FString FallbackPolicy = TEXT("policies/dummy_policy.onnx");
	/** shared/transition_table.json copy; relative paths resolve against Content/Project/RL_Policies. */
	UPROPERTY(EditAnywhere, Category = "Streetball") FString TransitionTablePath = TEXT("transition_table.json");
	UPROPERTY(EditAnywhere, Category = "Streetball") FString AudioBankPath = TEXT("/Game/Project/DataAssets/DA_CourtAudioBank.DA_CourtAudioBank");
	UPROPERTY(EditAnywhere, Category = "Streetball") int32 DirectorSeed = 7;
	UPROPERTY(EditAnywhere, Category = "Presentation") FString FXBankPath = TEXT("/Game/Project/DataAssets/DA_CourtFXBank.DA_CourtFXBank");
	UPROPERTY(EditAnywhere, Category = "Presentation") FString VoiceBankPath = TEXT("/Game/Project/DataAssets/DA_GrandmaVoiceBank.DA_GrandmaVoiceBank");
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
	int32 GetLocalScanCount() const { return LocalScanCount; }
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

	/**
	 * Dribble Lab (2026-11-24): the game focuses on the dribble skills. Behaviours are director settings on the one
	 * dribble family (same dribble.onnx): 0 right hand (tier 3), 1 left hand (tier 3), 2 crossover (tier 3, table hand
	 * switches), 3 moving (tier 4, right hand). Turned on in BeginPlay for the real game only (automation worlds keep
	 * the full tier run); -StreetballClassicHUD, -StreetballStartTier= or -StreetballDemoFeatures keep the classic HUD.
	 */
	static constexpr int32 NumDribbleBehaviours = 4;
	static const TCHAR* DribbleBehaviourName(int32 Behaviour);
	/** Passed its gate (docs/phase_reports/eval_*.md, docs/20261122/log.md): only the stationary right hand so far. */
	static bool IsDribbleBehaviourTrained(int32 Behaviour) { return Behaviour == 0; }
	void EnableDribbleFocus();
	bool IsDribbleFocus() const { return bDribbleFocus; }
	void SetDribbleBehaviour(int32 Behaviour);
	int32 GetDribbleBehaviour() const { return DribbleBehaviour; }
	/** Visual humanoid switch (same MuJoCo body and policies); re-initialises the bone mapper for the new skin. */
	bool SetHumanoid(int32 SkinIndex);
	void CycleHumanoid();
	/** Session counters since the last behaviour switch (HUD; tests). */
	int32 GetSessionResets() const { return ResetCount - SessionResetBase; }
	int32 GetSessionBounces() const { return SessionBounces; }
	double GetCurrentRunSeconds() const;
	double GetBestRunSeconds() const { return FMath::Max(BestRunS, GetCurrentRunSeconds()); }

	EStreetballAppMode GetAppMode() const { return AppMode; }
	bool IsPaused() const { return bPaused; }
	int32 GetNanInfCount() const { return NanInfCount; }
	float GetEpisodeReward() const { return EpisodeReward; }

private:
	void OnControlStep(UMuJoCoSim* InSim);
	void OnPhysicsStep(UMuJoCoSim* InSim);
	void HandlePlayerInput(float DeltaSeconds);
	void UpdateVisuals();
	void UpdatePresentation(float Dt);
	void SetupPresentation();
	void UpdateCaptureSchedule();
	UMaterialInterface* MaterialOverrideFor(const FString& GeomName) const;
	/** Local-only Megascans (Content/Art/megascans.json, git-ignored textures): swaps each listed override material for
	 *  a dynamic instance with the scan textures, only when every texture of that target loads. Returns targets applied. */
	int32 ApplyLocalScans();
	void UpdateCameraAndHUD(float Dt);
	/** Idle demo mode (StreetballShowcase): Watch mode, HUD hidden, showcase cameras; restored on input. */
	void HandleDemoMode(bool bActive);
	void HandleDemoCamera(FName CameraName, int32 Index);
	EStreetballAppMode PreDemoAppMode = EStreetballAppMode::Watch;
	uint8 PreDemoCameraMode = 0;
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
	UPROPERTY() TArray<TObjectPtr<AStreetballGeomActor>> DynamicGeomActors;
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
	int32 LocalScanCount = 0;
	float Exertion01 = 0.f;
	float LastPowerW = 0.f;
	double NextExertionSweatT = 0.0;
	FVector2d ActivePushForceSim = FVector2d::ZeroVector;
	double PushRemainingS = 0.0;
	int32 TimeScaleIdx = 2; // 0.25, 0.5, 1.0, 1.5, 2.0
	TArray<FString> RealPolicies;
	FStreetballDirectorOutput DirOut;
	FName LastPolicyName;
	// pre-sized scratch for the control step & render sync (UU_AGENT: no heap allocation in the real-time loop)
	TArray<float> CtrlBuf;
	TArray<double> QBuf, VBuf;
	TArray<FVector> BodyPosBuf;
	TArray<FQuat> BodyRotBuf;
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
	// Dribble Lab
	void HandleDribbleUiRequest(int32 Kind, int32 Index);
	bool bDribbleFocus = false;
	int32 DribbleBehaviour = 0;
	int32 SessionResetBase = 0;
	int32 SessionBounces = 0;
	int32 SessionCleanBounces = 0;
	double LastResetSimTime = 0.0;
	double BestRunS = 0.0;
	// face mood (smile grows with the clean streak, frown on failure)
	void UpdateFaceMood(float Dt);
	float FaceSmile = 0.f, FaceFrown = 0.f;
	int32 MoodResetCount = 0;
	bool bMoodLoose = false;
public:
	float GetFaceSmile() const { return FaceSmile; }
	float GetFaceFrown() const { return FaceFrown; }
	/** Clean bounces in a row for a full grin; seconds a frown takes to fade. */
	float FaceSmileFullStreak = 8.f;
	float FaceFrownFadeS = 2.5f;
	/** Tests: run the mood logic without the presentation tick. */
	void TickFaceMoodForTest(float Dt) { UpdateFaceMood(Dt); }
};
