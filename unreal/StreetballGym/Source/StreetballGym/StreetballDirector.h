#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "StreetballTracker.h"
#include "StreetballDirector.generated.h"

/** Blueprint C.3 runtime state machine states. */
UENUM(BlueprintType)
enum class EStreetballState : uint8
{
	Stand,
	Roam,
	DribbleStationary,
	DribbleMoving,
	JumpShot,
	Scramble,
	HardReset
};

/** What the world must do with the sim after a director update. */
struct STREETBALLGYM_API FStreetballResetSpec
{
	bool bRequested = false;
	bool bOffsetRoot = false;
	FVector2d RootXY = FVector2d::ZeroVector;   // sim metres
	double RootYaw = 0.0;                        // radians about +Z
	bool bPlaceBall = false;
	FVector3d BallPos = FVector3d::ZeroVector;   // sim metres
	FString Reason;
};

/** Per-step director output consumed by the world. */
struct STREETBALLGYM_API FStreetballDirectorOutput
{
	EStreetballState State = EStreetballState::Stand;
	FString PolicyName;                 // policy family, e.g. "locomotion"
	float Task[12] = {0};
	FStreetballResetSpec Reset;
	bool bScoreEvent = false;           // for the net-rattle sound
	bool bBounceEvent = false;
	bool bCleanBounce = false;
};

/** Counters the HUD shows (PRD section 6). */
struct STREETBALLGYM_API FStreetballProgress
{
	int32 ActiveTier = 1;               // 1..5
	FString TierName;
	bool Mastered[5] = {false, false, false, false, false};
	float Progress01 = 0.f;             // toward the active tier's milestone
	double BalanceTime = 0.0;           // tier 1
	int32 Waypoints = 0;                // tier 2
	int32 CleanStreak = 0;              // tier 3 (also live counter in later tiers)
	int32 HandSwitches = 0;
	double CourseDistance = 0.0;        // tier 4 metres
	int32 Saves = 0;                    // tier 4
	int32 ShotsTaken = 0, ShotsMade = 0;// tier 5
	double TotalDistance = 0.0;         // cumulative pelvis travel (HUD)
	bool bLoose = false;
	float CountdownFrac = 1.f;
};

/** One row of shared/transition_table.json "states". */
struct STREETBALLGYM_API FStreetballStateRow
{
	FString Policy;                     // family name ("balance", ...); empty for HARD_RESET
	int32 Tier = 0;
	FString Layout;                     // key into Layouts
	bool bHasSpeed = false;
	FVector2d SpeedRange = FVector2d::ZeroVector;   // [lo, hi]; lo == hi means fixed
	FIntPoint HandSwitchEvery = FIntPoint(0, 0);     // 0 = no commanded switches
};

/**
 * The autonomous "coach": picks the active skill policy family, builds its 12-float task block
 * from the layout in shared/transition_table.json (mirrors sim/streetball/levels/*.py), tracks
 * PRD tier milestones, runs the scramble countdown and orders hard resets. Pure logic over
 * FTrackedState so it is testable without a sim. Built-in defaults equal transition_table.json v1,
 * so it also works when the table file is absent.
 */
UCLASS()
class STREETBALLGYM_API UStreetballDirector : public UObject
{
	GENERATED_BODY()

public:
	void Initialize(int32 Seed = 7);

	/** Load states/policies/layouts from the transition table. Returns false (defaults kept) if unreadable. */
	bool LoadTransitionTable(const FString& JsonPath);
	bool HasTable() const { return bTableLoaded; }
	int32 TableVersion() const { return TableVersionNum; }

	/** One control step. S is the tracker state *after* this step; Dt is the control period. */
	void Update(const FTrackedState& S, double Dt, FStreetballDirectorOutput& Out);

	/** Must be called by the world after it applied a requested reset (so bookkeeping restarts cleanly). */
	void NotifyResetApplied(const FTrackedState& S);

	/** Tiers 1-2 never use the ball: park it where training parks it (l0_stand / l1_traverse on_reset). */
	static void ParkBallForTier(int32 Tier, FStreetballResetSpec& Spec);

	/** Fill State/PolicyName/Task for the current state without advancing any logic. */
	void Describe(const FTrackedState& S, FStreetballDirectorOutput& Out) const;

	EStreetballState GetState() const { return State; }
	const FStreetballProgress& GetProgress() const { return P; }
	static FString StateName(EStreetballState St);
	static bool StateFromName(const FString& Name, EStreetballState& Out);
	static int32 TierForState(EStreetballState St);

	/** Policy family for a state (table-driven; HARD_RESET maps to the active tier's state). */
	FString PolicyFor(EStreetballState St) const;
	/** Relative file for a family from the table ("policies/balance.onnx"); empty if unknown. */
	FString PolicyFileFor(const FString& Family) const;
	const TMap<FString, FString>& GetPolicyFiles() const { return PolicyFiles; }
	const TArray<FString>& LayoutFor(const FString& Layout) const;
	const FStreetballStateRow* RowFor(EStreetballState St) const { return Rows.Find(St); }

	/** Test hooks. */
	void ForceState(EStreetballState St, const FTrackedState& S);
	void SetMastered(int32 Tier, bool bValue) { if (Tier >= 1 && Tier <= 5) P.Mastered[Tier - 1] = bValue; }

	// ---- tunables (PRD / blueprint) ----
	double BalanceGoalS = 60.0;
	/** Highest tier the run may advance to (command line -StreetballMaxTier=N). A mastered tier at the cap restarts its goal. */
	int32 MaxTier = 5;
	double FootDriftLimit = 0.15;
	int32 WaypointGoal = 10;
	double ReachRadius = 0.5;
	FVector2d CourtHalf = FVector2d(13.0, 6.5);
	int32 StreakGoal = 50;
	FVector2d ApexBand = FVector2d(0.80, 1.15);
	double ApexTarget = 1.0;
	double CourseGoal = 100.0;
	int32 SavesGoal = 3;
	int32 ShotsGoal = 20;
	double ShotFgGoal = 0.30;
	double ShotTimeout = 8.0;
	double ScrambleS = 3.0;

private:
	void InstallDefaultTable();
	void EnterState(EStreetballState St, const FTrackedState& S);
	void EnterTier(int32 Tier, const FTrackedState& S);
	void NewWaypoint(const FTrackedState& S);
	void SetHand(bool bRandom, const FTrackedState& S);
	void UpdateBounce(const FTrackedState& S, FStreetballDirectorOutput& Out);
	void RequestHardReset(const TCHAR* Reason, FStreetballDirectorOutput& Out);
	void RequestShotReset(FStreetballDirectorOutput& Out);
	void FillTask(const FTrackedState& S, FStreetballDirectorOutput& Out) const;
	double TaskField(const FString& Field, const FTrackedState& S) const;

	// table
	TMap<EStreetballState, FStreetballStateRow> Rows;
	TMap<FString, TArray<FString>> Layouts;
	TMap<FString, FString> PolicyFiles;
	bool bTableLoaded = false;
	int32 TableVersionNum = 0;

	EStreetballState State = EStreetballState::Stand;
	EStreetballState ReturnState = EStreetballState::DribbleStationary;   // where Scramble returns to
	EStreetballState TierState = EStreetballState::Stand;                 // state the active tier runs in
	FStreetballProgress P;
	FRandomStream Rng;

	// tier 1
	FVector2d FootStart[2];
	bool bFootStartValid = false;
	// tier 2 / 4
	FVector2d Waypoint = FVector2d::ZeroVector;
	double SpeedCmd = 1.0;
	FVector2d LastPelvisXY = FVector2d::ZeroVector;
	bool bLastPelvisValid = false;
	// tier 3
	double Hand = 1.0;                  // +1 right, -1 left
	int32 UntilSwitch = 3;
	bool bPrevFloor = false, bPalmSince = true, bNearSince = true;
	double Apex = 0.0;
	// tier 5
	bool bTriggered = false, bGathered = false, bReleased = false, bScored = false;
	double TriggerT = 0.0, ShotStartT = 0.0, PrevBallZ = 0.0;
	int32 RimIndex = 0;
	double LastStateChangeT = 0.0;
};
