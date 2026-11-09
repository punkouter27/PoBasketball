#include "StreetballDirector.h"
#include "StreetballGym.h"
#include "Misc/FileHelper.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	constexpr double RimH = 3.05;
	constexpr double RimR = 0.2286;
	constexpr double KeyBallX = 0.45, KeyBallY = -0.35, BallR = 0.1205;   // ball offset in the 'stand' keyframe
	constexpr double KeyRootX = 0.02281, KeyRootY = 0.0;                  // root xy in the 'stand' keyframe
	const TArray<FString> EmptyLayout;
}

// ---------------------------------------------------------------------------- names
FString UStreetballDirector::StateName(EStreetballState St)
{
	switch (St)
	{
	case EStreetballState::Stand: return TEXT("STAND");
	case EStreetballState::Roam: return TEXT("ROAM");
	case EStreetballState::DribbleStationary: return TEXT("DRIBBLE_STATIONARY");
	case EStreetballState::DribbleMoving: return TEXT("DRIBBLE_MOVING");
	case EStreetballState::JumpShot: return TEXT("JUMP_SHOT");
	case EStreetballState::Scramble: return TEXT("SCRAMBLE");
	default: return TEXT("HARD_RESET");
	}
}

bool UStreetballDirector::StateFromName(const FString& Name, EStreetballState& Out)
{
	static const EStreetballState All[] = {EStreetballState::Stand, EStreetballState::Roam, EStreetballState::DribbleStationary,
		EStreetballState::DribbleMoving, EStreetballState::JumpShot, EStreetballState::Scramble, EStreetballState::HardReset};
	for (EStreetballState S : All) if (StateName(S) == Name) { Out = S; return true; }
	return false;
}

int32 UStreetballDirector::TierForState(EStreetballState St)
{
	switch (St)
	{
	case EStreetballState::Stand: return 1;
	case EStreetballState::Roam: return 2;
	case EStreetballState::DribbleStationary: return 3;
	case EStreetballState::DribbleMoving: return 4;
	case EStreetballState::JumpShot: return 5;
	default: return 0;
	}
}

// ---------------------------------------------------------------------------- transition table
void UStreetballDirector::InstallDefaultTable()
{
	// Identical to shared/transition_table.json v1 so the director works without the file.
	Rows.Reset(); Layouts.Reset(); PolicyFiles.Reset();
	auto Row = [&](EStreetballState S, const TCHAR* Policy, int32 Tier, const TCHAR* Layout, double Lo, double Hi, bool bSpeed, FIntPoint Sw)
	{
		FStreetballStateRow R; R.Policy = (Policy && *Policy) ? FName(Policy) : NAME_None; R.Tier = Tier; R.Layout = Layout; R.bHasSpeed = bSpeed; R.SpeedRange = FVector2d(Lo, Hi); R.HandSwitchEvery = Sw;
		Rows.Add(S, R);
	};
	Row(EStreetballState::Stand, TEXT("balance"), 1, TEXT("balance"), 0, 0, false, FIntPoint(0, 0));
	Row(EStreetballState::Roam, TEXT("locomotion"), 2, TEXT("locomotion"), 1.2, 3.0, true, FIntPoint(0, 0));
	Row(EStreetballState::DribbleStationary, TEXT("dribble"), 3, TEXT("dribble"), 0.0, 0.0, true, FIntPoint(2, 4));
	Row(EStreetballState::DribbleMoving, TEXT("dribble"), 4, TEXT("dribble"), 1.5, 2.5, true, FIntPoint(0, 0));
	Row(EStreetballState::JumpShot, TEXT("shot"), 5, TEXT("shot"), 0, 0, false, FIntPoint(0, 0));
	Row(EStreetballState::Scramble, TEXT("scramble"), 0, TEXT("scramble"), 0, 0, false, FIntPoint(0, 0));
	Row(EStreetballState::HardReset, TEXT(""), 0, TEXT(""), 0, 0, false, FIntPoint(0, 0));
	Layouts.Add(TEXT("balance"), {TEXT("0")});
	Layouts.Add(TEXT("locomotion"), {TEXT("dir_x"), TEXT("dir_y"), TEXT("distance_m"), TEXT("speed_cmd")});
	Layouts.Add(TEXT("dribble"), {TEXT("hand"), TEXT("apex_target_m"), TEXT("bounces_to_switch"), TEXT("speed_cmd"), TEXT("dir_x"), TEXT("dir_y"), TEXT("distance_m")});
	Layouts.Add(TEXT("scramble"), {TEXT("countdown_frac")});
	Layouts.Add(TEXT("shot"), {TEXT("rim_rel_x"), TEXT("rim_rel_y"), TEXT("rim_rel_z"), TEXT("trigger"), TEXT("time_since_trigger_s")});
	PolicyFiles.Add(TEXT("balance"), TEXT("policies/balance.onnx"));
	PolicyFiles.Add(TEXT("locomotion"), TEXT("policies/locomotion.onnx"));
	PolicyFiles.Add(TEXT("dribble"), TEXT("policies/dribble.onnx"));
	PolicyFiles.Add(TEXT("scramble"), TEXT("policies/scramble.onnx"));
	PolicyFiles.Add(TEXT("shot"), TEXT("policies/shot.onnx"));
	bTableLoaded = false;
	TableVersionNum = 1;
}

bool UStreetballDirector::LoadTransitionTable(const FString& Path)
{
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Path))
	{
		UE_LOG(LogStreetball, Warning, TEXT("Director: transition table %s not found; using built-in v1 defaults"), *Path);
		return false;
	}
	TSharedPtr<FJsonObject> J;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), J) || !J.IsValid())
	{
		UE_LOG(LogStreetball, Error, TEXT("Director: bad JSON in %s; using built-in defaults"), *Path);
		return false;
	}
	TMap<EStreetballState, FStreetballStateRow> NewRows;
	TMap<FString, TArray<FString>> NewLayouts;
	TMap<FString, FString> NewFiles;

	const TSharedPtr<FJsonObject> Pol = J->GetObjectField(TEXT("policies"));
	for (const TPair<FString, TSharedPtr<FJsonValue>>& E : Pol->Values)
	{
		const TSharedPtr<FJsonObject> O = E.Value->AsObject();
		if (O.IsValid()) NewFiles.Add(E.Key, O->GetStringField(TEXT("file")));
	}
	const TSharedPtr<FJsonObject> Lay = J->GetObjectField(TEXT("task_block_layouts"));
	for (const TPair<FString, TSharedPtr<FJsonValue>>& E : Lay->Values)
	{
		TArray<FString> Fields;
		for (const TSharedPtr<FJsonValue>& V : E.Value->AsArray()) Fields.Add(V->AsString());
		if (Fields.Num() > 12) { UE_LOG(LogStreetball, Error, TEXT("Director: layout %s has %d fields (> 12)"), *E.Key, Fields.Num()); return false; }
		NewLayouts.Add(E.Key, Fields);
	}
	const TSharedPtr<FJsonObject> States = J->GetObjectField(TEXT("states"));
	for (const TPair<FString, TSharedPtr<FJsonValue>>& E : States->Values)
	{
		EStreetballState St;
		if (!StateFromName(E.Key, St)) { UE_LOG(LogStreetball, Warning, TEXT("Director: unknown state %s in table"), *E.Key); continue; }
		const TSharedPtr<FJsonObject> O = E.Value->AsObject();
		FStreetballStateRow R;
		if (O->HasTypedField<EJson::String>(TEXT("policy"))) R.Policy = FName(*O->GetStringField(TEXT("policy")));
		if (O->HasTypedField<EJson::Number>(TEXT("tier"))) R.Tier = (int32)O->GetNumberField(TEXT("tier"));
		const TSharedPtr<FJsonObject>* Task = nullptr;
		if (O->TryGetObjectField(TEXT("task"), Task) && Task && Task->IsValid())
		{
			R.Layout = (*Task)->GetStringField(TEXT("layout"));
			const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
			if ((*Task)->HasTypedField<EJson::Number>(TEXT("speed_cmd"))) { R.bHasSpeed = true; const double V = (*Task)->GetNumberField(TEXT("speed_cmd")); R.SpeedRange = FVector2d(V, V); }
			else if ((*Task)->TryGetArrayField(TEXT("speed_cmd"), Arr) && Arr->Num() == 2) { R.bHasSpeed = true; R.SpeedRange = FVector2d((*Arr)[0]->AsNumber(), (*Arr)[1]->AsNumber()); }
			if ((*Task)->TryGetArrayField(TEXT("hand_switch_every"), Arr) && Arr->Num() == 2) R.HandSwitchEvery = FIntPoint((int32)(*Arr)[0]->AsNumber(), (int32)(*Arr)[1]->AsNumber());
		}
		if (!R.Policy.IsNone() && !NewFiles.Contains(R.Policy.ToString())) { UE_LOG(LogStreetball, Error, TEXT("Director: state %s uses unknown policy %s"), *E.Key, *R.Policy.ToString()); return false; }
		if (!R.Layout.IsEmpty() && !NewLayouts.Contains(R.Layout)) { UE_LOG(LogStreetball, Error, TEXT("Director: state %s uses unknown layout %s"), *E.Key, *R.Layout); return false; }
		NewRows.Add(St, R);
	}
	for (EStreetballState S : {EStreetballState::Stand, EStreetballState::Roam, EStreetballState::DribbleStationary, EStreetballState::DribbleMoving, EStreetballState::JumpShot, EStreetballState::Scramble})
	{
		if (!NewRows.Contains(S)) { UE_LOG(LogStreetball, Error, TEXT("Director: table lacks state %s"), *StateName(S)); return false; }
	}
	Rows = MoveTemp(NewRows); Layouts = MoveTemp(NewLayouts); PolicyFiles = MoveTemp(NewFiles);
	TableVersionNum = J->HasField(TEXT("version")) ? (int32)J->GetNumberField(TEXT("version")) : 0;
	bTableLoaded = true;
	UE_LOG(LogStreetball, Log, TEXT("Director: loaded transition table v%d from %s (%d states, %d policies, %d layouts)"), TableVersionNum, *Path, Rows.Num(), PolicyFiles.Num(), Layouts.Num());
	return true;
}

FName UStreetballDirector::PolicyFor(EStreetballState St) const
{
	if (St == EStreetballState::HardReset) St = TierState;
	const FStreetballStateRow* R = Rows.Find(St);
	return R ? R->Policy : NAME_None;
}

FString UStreetballDirector::PolicyFileFor(const FString& Family) const
{
	const FString* F = PolicyFiles.Find(Family);
	return F ? *F : FString();
}

const TArray<FString>& UStreetballDirector::LayoutFor(const FString& Layout) const
{
	const TArray<FString>* L = Layouts.Find(Layout);
	return L ? *L : EmptyLayout;
}

// ---------------------------------------------------------------------------- lifecycle
void UStreetballDirector::Initialize(int32 Seed)
{
	Rng.Initialize(Seed);
	P = FStreetballProgress();
	if (Rows.Num() == 0) InstallDefaultTable();
	FTrackedState S;
	EnterTier(1, S);
}

void UStreetballDirector::ForceState(EStreetballState St, const FTrackedState& S)
{
	const int32 Tier = TierForState(St);
	if (Tier > 0) EnterTier(Tier, S);
	else EnterState(St, S);
}

void UStreetballDirector::EnterState(EStreetballState St, const FTrackedState& S)
{
	State = St;
	LastStateChangeT = S.Time;
}

void UStreetballDirector::EnterTier(int32 Tier, const FTrackedState& S)
{
	P.ActiveTier = Tier;
	switch (Tier)
	{
	case 1: TierState = EStreetballState::Stand; P.TierName = TEXT("Tier 1: Upright Balance"); P.BalanceTime = 0.0; bFootStartValid = false; break;
	case 2: TierState = EStreetballState::Roam; P.TierName = TEXT("Tier 2: Court Traversal"); P.Waypoints = 0; break;
	case 3: TierState = EStreetballState::DribbleStationary; P.TierName = TEXT("Tier 3: Stationary Dribble"); P.CleanStreak = 0; P.HandSwitches = 0; break;
	case 4: TierState = EStreetballState::DribbleMoving; P.TierName = TEXT("Tier 4: Dynamic Roam & Dribble"); P.CourseDistance = 0.0; P.Saves = 0; P.CleanStreak = 0; break;
	default: TierState = EStreetballState::JumpShot; P.TierName = TEXT("Tier 5: Pull-Up Jump Shot"); P.ShotsTaken = 0; P.ShotsMade = 0; P.CleanStreak = 0; break;
	}
	EnterState(TierState, S);
	if (bHandPreset) bHandPreset = false;          // the reset placed the ball for this hand
	else SetHand(Tier == 3 || Tier == 4, S);
	NewWaypoint(S);
	bPrevFloor = false; bPalmSince = true; bNearSince = true; Apex = S.BallPos.Z;
	bTriggered = bGathered = bReleased = bScored = false;
	ShotStartT = S.Time; TriggerT = Rng.FRandRange(1.0, 3.0); PrevBallZ = S.BallPos.Z;
	P.Progress01 = 0.f;
}

void UStreetballDirector::NewWaypoint(const FTrackedState&)
{
	Waypoint = FVector2d(Rng.FRandRange(-CourtHalf.X, CourtHalf.X), Rng.FRandRange(-CourtHalf.Y, CourtHalf.Y));
	const FStreetballStateRow* R = Rows.Find(TierState);
	if (R && R->bHasSpeed) SpeedCmd = (R->SpeedRange.X == R->SpeedRange.Y) ? R->SpeedRange.X : Rng.FRandRange(R->SpeedRange.X, R->SpeedRange.Y);
	else SpeedCmd = 0.0;
}

void UStreetballDirector::SetHand(bool bRandom, const FTrackedState&)
{
	if (ForcedHand != 0.0) { Hand = ForcedHand; UntilSwitch = 0; return; }
	Hand = (bRandom && Rng.FRand() < 0.5) ? -1.0 : 1.0;
	const FStreetballStateRow* R = Rows.Find(TierState);
	UntilSwitch = (R && R->HandSwitchEvery.Y > 0) ? Rng.RandRange(R->HandSwitchEvery.X, R->HandSwitchEvery.Y) : 0;
}

void UStreetballDirector::RequestHardReset(const TCHAR* Reason, FStreetballDirectorOutput& Out)
{
	Out.Reset.bRequested = true;
	Out.Reset.Reason = Reason;
	if (P.ActiveTier == 5) { Out.Reset = FStreetballResetSpec(); RequestShotReset(Out); Out.Reset.Reason = Reason; }
	PrepareReset(P.ActiveTier, Out.Reset);
	State = EStreetballState::HardReset;          // the world logs the reset outside the control step
}

void UStreetballDirector::ParkBallForTier(int32 Tier, FStreetballResetSpec& Spec)
{
	// The keyframe leaves the ball on the floor beside the right foot. Balance never trained with a ball
	// there and trips over it (100 % falls at 1.4 s), so tiers 1-2 mirror the sim resets instead.
	if (Tier == 1) { Spec.bPlaceBall = true; Spec.BallPos = FVector3d(KeyRootX + 3.0, KeyRootY, BallR); }   // l0_stand: 3 m away
	else if (Tier == 2) { Spec.bPlaceBall = true; Spec.BallPos = FVector3d(0.0, 8.0, BallR); }            // l1_traverse: off court
}

void UStreetballDirector::PrepareReset(int32 Tier, FStreetballResetSpec& Spec)
{
	ParkBallForTier(Tier, Spec);
	if (Tier != 3 && Tier != 4) return;
	// Mirrors sim l2_dribble.on_reset (tier 3) / l3_roam.L3MovingDribble.on_reset (tier 4): ball at the active
	// hand's dribble spot at a random point of a dribble cycle, h ~ U(0.40, 0.95) m, vz = -/+ sqrt(2 g (1 - h)).
	// Before 2026-11-08 the ball stayed at its keyframe spot on the floor and the policy fell ~1.2 s after every reset.
	static const FTrackedState NoState{};
	SetHand(true, NoState);
	bHandPreset = true;
	Spec.bDribbleStart = true;
	Spec.DribbleHand = Hand;
	Spec.DribbleSpotFwd = Tier == 3 ? 0.25 : 0.30;
	Spec.DribbleSpotSide = 0.35;
	const double H = Rng.FRandRange(DribbleStartHeight.X, DribbleStartHeight.Y);
	Spec.BallStartZ = H;
	Spec.BallStartVz = -FMath::Sqrt(2.0 * 9.81 * FMath::Max(0.0, 1.0 - H)) * (Rng.FRand() < 0.5 ? 1.0 : -1.0);
}

void UStreetballDirector::StartAtTier(int32 Tier)
{
	Tier = FMath::Clamp(Tier, 1, 5);
	for (int32 i = 0; i < Tier - 1; ++i) P.Mastered[i] = true;
	FTrackedState S;
	EnterTier(Tier, S);
}

void UStreetballDirector::RequestShotReset(FStreetballDirectorOutput& Out)
{
	// Random spot inside the 6.75 m arc, facing the east rim; ball under the right hand.
	const FVector2d Rim(12.425, 0.0);
	const double Dist = Rng.FRandRange(2.0, 6.5);
	const double Ang = FMath::DegreesToRadians(Rng.FRandRange(-60.0, 60.0));
	FVector2d Spot(Rim.X - Dist * FMath::Cos(Ang), Rim.Y - Dist * FMath::Sin(Ang));
	Spot.X = FMath::Min(Spot.X, Rim.X - 1.5);
	const double Yaw = FMath::Atan2(Rim.Y - Spot.Y, Rim.X - Spot.X);
	Out.Reset.bRequested = true;
	Out.Reset.bOffsetRoot = true;
	Out.Reset.RootXY = Spot;
	Out.Reset.RootYaw = Yaw;
	Out.Reset.bPlaceBall = true;
	const double c = FMath::Cos(Yaw), s = FMath::Sin(Yaw);
	Out.Reset.BallPos = FVector3d(Spot.X + c * KeyBallX - s * KeyBallY, Spot.Y + s * KeyBallX + c * KeyBallY, BallR);
	Out.Reset.Reason = TEXT("new shot");
	RimIndex = 0;
}

void UStreetballDirector::NotifyResetApplied(const FTrackedState& S)
{
	// PRD section 5: a hard reset restarts the active tier; mastered tiers stay mastered.
	const int32 Tier = P.ActiveTier;
	const int32 Taken = P.ShotsTaken, Made = P.ShotsMade;
	EnterTier(Tier, S);
	if (Tier == 5) { P.ShotsTaken = Taken; P.ShotsMade = Made; }   // shots are attempts, not a streak
	bLastPelvisValid = false;
}

// ---------------------------------------------------------------------------- task block
double UStreetballDirector::TaskField(const FString& F, const FTrackedState& S) const
{
	const FStreetballStateRow* R = Rows.Find(State == EStreetballState::HardReset ? TierState : State);
	const bool bMoves = R && R->bHasSpeed && !(R->SpeedRange.X == 0.0 && R->SpeedRange.Y == 0.0);
	if (F == TEXT("0")) return 0.0;
	if (F == TEXT("dir_x") || F == TEXT("dir_y") || F == TEXT("distance_m"))
	{
		if (!bMoves) return 0.0;                                   // stationary dribble: no waypoint
		const FVector2d Rel = Waypoint - FVector2d(S.PelvisPos.X, S.PelvisPos.Y);
		const double Dist = Rel.Length();
		if (F == TEXT("distance_m")) return FMath::Min(Dist, 10.0);
		const FVector2d Dir = S.ToHeading(Dist > 1e-6 ? Rel / Dist : FVector2d(1, 0));
		return F == TEXT("dir_x") ? Dir.X : Dir.Y;
	}
	if (F == TEXT("speed_cmd")) return bMoves ? SpeedCmd : 0.0;
	if (F == TEXT("hand")) return Hand;
	if (F == TEXT("apex_target_m")) return ApexTarget;
	if (F == TEXT("bounces_to_switch")) return (ForcedHand == 0.0 && R && R->HandSwitchEvery.Y > 0) ? (double)UntilSwitch : 0.0;
	if (F == TEXT("countdown_frac")) return S.CountdownFrac;
	if (F == TEXT("trigger")) return bTriggered ? 1.0 : 0.0;
	if (F == TEXT("time_since_trigger_s")) return bTriggered ? FMath::Max(0.0, S.Time - (ShotStartT + TriggerT)) : 0.0;
	if (F.StartsWith(TEXT("rim_rel_")))
	{
		const FVector3d Rel = S.RimPos[RimIndex] - S.PelvisPos;
		const FVector2d H = S.ToHeading(FVector2d(Rel.X, Rel.Y));
		if (F == TEXT("rim_rel_x")) return H.X;
		if (F == TEXT("rim_rel_y")) return H.Y;
		return Rel.Z;
	}
	return 0.0;
}

void UStreetballDirector::FillTask(const FTrackedState& S, FStreetballDirectorOutput& Out) const
{
	FMemory::Memzero(Out.Task);
	const FStreetballStateRow* R = Rows.Find(State == EStreetballState::HardReset ? TierState : State);
	if (!R) return;
	const TArray<FString>& L = LayoutFor(R->Layout);
	for (int32 i = 0; i < L.Num() && i < 12; ++i) Out.Task[i] = (float)TaskField(L[i], S);
}

void UStreetballDirector::Describe(const FTrackedState& S, FStreetballDirectorOutput& Out) const
{
	Out = FStreetballDirectorOutput();
	Out.State = State;
	Out.PolicyName = PolicyFor(State);
	FillTask(S, Out);
}

// ---------------------------------------------------------------------------- bounce bookkeeping (l2_dribble.py)
void UStreetballDirector::UpdateBounce(const FTrackedState& S, FStreetballDirectorOutput& Out)
{
	const bool Floor = S.BallFloor;
	const bool Bounce = Floor && !bPrevFloor;
	bPrevFloor = Floor;
	const double ApexBefore = Apex;
	Apex = Bounce ? S.BallPos.Z : FMath::Max(Apex, S.BallPos.Z);
	const double Horiz = FVector2d(S.BallPos.X - S.PelvisPos.X, S.BallPos.Y - S.PelvisPos.Y).Length();
	bNearSince = bNearSince && Horiz < 0.6;
	const bool ActivePalm = Hand > 0 ? S.PalmBall[1] : S.PalmBall[0];
	bPalmSince = bPalmSince || ActivePalm;
	const bool Clean = Bounce && bPalmSince && bNearSince && ApexBefore >= ApexBand.X && ApexBefore <= ApexBand.Y;
	if (Clean) ++P.CleanStreak; else if (Bounce) P.CleanStreak = 0;
	const FStreetballStateRow* R = Rows.Find(State);
	if (Clean && R && R->HandSwitchEvery.Y > 0 && ForcedHand == 0.0)                    // commanded crossover only where the table says so
	{
		if (--UntilSwitch <= 0) { Hand = -Hand; ++P.HandSwitches; UntilSwitch = Rng.RandRange(R->HandSwitchEvery.X, R->HandSwitchEvery.Y); }
	}
	if (Bounce) { bPalmSince = false; bNearSince = true; }
	Out.bBounceEvent = Bounce;
	Out.bCleanBounce = Clean;
}

// ---------------------------------------------------------------------------- update
void UStreetballDirector::Update(const FTrackedState& S, double Dt, FStreetballDirectorOutput& Out)
{
	Out = FStreetballDirectorOutput();
	const FVector2d PelvisXY(S.PelvisPos.X, S.PelvisPos.Y);
	const double Moved = bLastPelvisValid ? (PelvisXY - LastPelvisXY).Length() : 0.0;
	LastPelvisXY = PelvisXY; bLastPelvisValid = true;
	P.TotalDistance += Moved;
	P.CountdownFrac = S.CountdownFrac;
	const bool BallStates = State == EStreetballState::DribbleStationary || State == EStreetballState::DribbleMoving ||
	                        State == EStreetballState::JumpShot || State == EStreetballState::Scramble;
	P.bLoose = BallStates && S.LooseT >= 0.0;

	if (State == EStreetballState::HardReset)
	{
		Out.Reset.bRequested = true;
		Out.State = State; Out.PolicyName = PolicyFor(TierState);
		return;
	}
	if (S.Fallen) { RequestHardReset(TEXT("fallen"), Out); Out.State = State; Out.PolicyName = PolicyFor(TierState); return; }
	if (S.BallOutOfFence) { RequestHardReset(TEXT("ball past fence"), Out); Out.State = State; Out.PolicyName = PolicyFor(TierState); return; }

	switch (State)
	{
	case EStreetballState::Stand:
	{
		if (!bFootStartValid) { FootStart[0] = S.FootPos[0]; FootStart[1] = S.FootPos[1]; bFootStartValid = true; }
		const bool Stepped = (S.FootPos[0] - FootStart[0]).Length() > FootDriftLimit || (S.FootPos[1] - FootStart[1]).Length() > FootDriftLimit;
		if (Stepped) { P.BalanceTime = 0.0; FootStart[0] = S.FootPos[0]; FootStart[1] = S.FootPos[1]; }
		else P.BalanceTime += Dt;
		P.Progress01 = (float)FMath::Clamp(P.BalanceTime / BalanceGoalS, 0.0, 1.0);
		if (P.BalanceTime >= BalanceGoalS) { P.Mastered[0] = true; EnterTier(MaxTier >= 2 ? 2 : 1, S); }
		break;
	}
	case EStreetballState::Roam:
	{
		if ((Waypoint - PelvisXY).Length() < ReachRadius) { ++P.Waypoints; NewWaypoint(S); }
		P.Progress01 = (float)FMath::Clamp((double)P.Waypoints / WaypointGoal, 0.0, 1.0);
		if (P.Waypoints >= WaypointGoal)
		{
			P.Mastered[1] = true;
			if (MaxTier < 3) { EnterTier(2, S); break; }
			EnterTier(3, S);
			Out.Reset.bRequested = true; Out.Reset.Reason = TEXT("tier 3 start: ball to hand"); PrepareReset(3, Out.Reset);
		}
		break;
	}
	case EStreetballState::DribbleStationary:
	{
		UpdateBounce(S, Out);
		P.Progress01 = (float)FMath::Clamp((double)P.CleanStreak / StreakGoal, 0.0, 1.0);
		if (S.LooseT >= 0.0) { ReturnState = State; EnterState(EStreetballState::Scramble, S); break; }
		if (P.CleanStreak >= StreakGoal)
		{
			P.Mastered[2] = true;
			if (MaxTier < 4) { EnterTier(3, S); break; }
			EnterTier(4, S);
			Out.Reset.bRequested = true; Out.Reset.Reason = TEXT("tier 4 start"); PrepareReset(4, Out.Reset);
		}
		break;
	}
	case EStreetballState::DribbleMoving:
	{
		UpdateBounce(S, Out);
		if (S.InControl) P.CourseDistance += Moved;
		if ((Waypoint - PelvisXY).Length() < ReachRadius) NewWaypoint(S);
		P.Progress01 = (float)FMath::Clamp(0.7 * P.CourseDistance / CourseGoal + 0.3 * FMath::Min(1.0, (double)P.Saves / SavesGoal), 0.0, 1.0);
		if (S.LooseT >= 0.0) { ReturnState = State; EnterState(EStreetballState::Scramble, S); break; }
		if (P.CourseDistance >= CourseGoal && P.Saves >= SavesGoal)
		{
			P.Mastered[3] = true;
			if (MaxTier < 5) { EnterTier(4, S); break; }
			EnterTier(5, S);
			RequestShotReset(Out);
		}
		break;
	}
	case EStreetballState::JumpShot:
	{
		if (!bTriggered)
		{
			UpdateBounce(S, Out);
			if (S.LooseT >= 0.0) { ReturnState = State; EnterState(EStreetballState::Scramble, S); break; }
			if (S.Time - ShotStartT >= TriggerT) bTriggered = true;
		}
		else
		{
			const bool Both = S.PalmBall[0] && S.PalmBall[1];
			const bool None = !S.PalmBall[0] && !S.PalmBall[1];
			bGathered = bGathered || Both;
			if (bGathered && !bReleased && None && S.BallPos.Z > 1.6) bReleased = true;
			bool Resolved = false;
			if (bReleased)
			{
				const FVector3d Rel = S.BallPos - S.RimPos[RimIndex];
				const double Horiz = FVector2d(Rel.X, Rel.Y).Length();
				const bool Crossing = PrevBallZ > RimH && S.BallPos.Z <= RimH && Horiz < RimR - 0.08;
				if (Crossing && !bScored) { bScored = true; Out.bScoreEvent = true; Resolved = true; }
				else if (S.BallFloor) Resolved = true;
			}
			else if (!bReleased && S.LooseT >= 0.0) { ReturnState = State; EnterState(EStreetballState::Scramble, S); break; }
			if (!Resolved && S.Time - (ShotStartT + TriggerT) > ShotTimeout) Resolved = true;
			if (Resolved)
			{
				++P.ShotsTaken; if (bScored) ++P.ShotsMade;
				if (P.ShotsTaken >= ShotsGoal)
				{
					if ((double)P.ShotsMade / P.ShotsTaken >= ShotFgGoal) P.Mastered[4] = true;
					else { P.ShotsTaken = 0; P.ShotsMade = 0; }
				}
				RequestShotReset(Out);
				State = EStreetballState::HardReset;    // world applies the spec then NotifyResetApplied
			}
		}
		PrevBallZ = S.BallPos.Z;
		P.Progress01 = (float)FMath::Clamp((double)P.ShotsTaken / ShotsGoal, 0.0, 1.0);
		break;
	}
	case EStreetballState::Scramble:
	{
		if (S.InControl)
		{
			if (ReturnState == EStreetballState::DribbleMoving) ++P.Saves;
			bPrevFloor = S.BallFloor; bPalmSince = true; bNearSince = true; Apex = S.BallPos.Z;
			EnterState(ReturnState, S);
		}
		else if (S.CountdownFrac <= 0.f || (S.Time - S.LooseT) >= ScrambleS)
		{
			RequestHardReset(TEXT("scramble countdown expired"), Out);
		}
		break;
	}
	default: break;
	}

	Out.State = State;
	Out.PolicyName = PolicyFor(State);
	FillTask(S, Out);
}
