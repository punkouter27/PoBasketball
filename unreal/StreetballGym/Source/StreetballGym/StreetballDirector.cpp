#include "StreetballDirector.h"
#include "StreetballGym.h"

namespace
{
	constexpr double RimH = 3.05;
	constexpr double RimR = 0.2286;
	constexpr double KeyBallX = 0.45, KeyBallY = -0.35, BallR = 0.1205;   // ball offset in the 'stand' keyframe
}

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

FString UStreetballDirector::PolicyForState(EStreetballState St)
{
	switch (St)
	{
	case EStreetballState::Stand: return TEXT("l0_stand");
	case EStreetballState::Roam: return TEXT("l1_traverse");
	case EStreetballState::DribbleStationary: return TEXT("l2c_crossover");
	case EStreetballState::DribbleMoving: return TEXT("l3a_moving_dribble");
	case EStreetballState::JumpShot: return TEXT("l4_jump_shot");
	case EStreetballState::Scramble: return TEXT("l3b_scramble");
	default: return TEXT("l0_stand");
	}
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

void UStreetballDirector::Initialize(int32 Seed)
{
	Rng.Initialize(Seed);
	P = FStreetballProgress();
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
	case 2: TierState = EStreetballState::Roam; P.TierName = TEXT("Tier 2: Court Traversal"); P.Waypoints = 0; NewWaypoint(S); break;
	case 3: TierState = EStreetballState::DribbleStationary; P.TierName = TEXT("Tier 3: Stationary Dribble"); P.CleanStreak = 0; P.HandSwitches = 0; SetHand(true, S); break;
	case 4: TierState = EStreetballState::DribbleMoving; P.TierName = TEXT("Tier 4: Dynamic Roam & Dribble"); P.CourseDistance = 0.0; P.Saves = 0; P.CleanStreak = 0; SetHand(true, S); NewWaypoint(S); break;
	default: TierState = EStreetballState::JumpShot; P.TierName = TEXT("Tier 5: Pull-Up Jump Shot"); P.ShotsTaken = 0; P.ShotsMade = 0; P.CleanStreak = 0; SetHand(false, S); break;
	}
	bPrevFloor = false; bPalmSince = true; bNearSince = true; Apex = S.BallPos.Z;
	bTriggered = bGathered = bReleased = bScored = false;
	ShotStartT = S.Time; TriggerT = Rng.FRandRange(1.0, 3.0); PrevBallZ = S.BallPos.Z;
	P.Progress01 = 0.f;
	EnterState(TierState, S);
}

void UStreetballDirector::NewWaypoint(const FTrackedState& S)
{
	Waypoint = FVector2d(Rng.FRandRange(-CourtHalf.X, CourtHalf.X), Rng.FRandRange(-CourtHalf.Y, CourtHalf.Y));
	const FVector2d R = (P.ActiveTier >= 4) ? RoamSpeedRange : SpeedRange;
	SpeedCmd = Rng.FRandRange(R.X, R.Y);
}

void UStreetballDirector::SetHand(bool bRandom, const FTrackedState&)
{
	Hand = (bRandom && Rng.FRand() < 0.5) ? -1.0 : 1.0;
	UntilSwitch = Rng.RandRange(2, 4);
}

void UStreetballDirector::RequestHardReset(const TCHAR* Reason, FStreetballDirectorOutput& Out)
{
	Out.Reset.bRequested = true;
	Out.Reset.Reason = Reason;
	if (P.ActiveTier == 5) { Out.Reset = FStreetballResetSpec(); RequestShotReset(Out); Out.Reset.Reason = Reason; }
	State = EStreetballState::HardReset;
	UE_LOG(LogStreetball, Log, TEXT("Director: HARD_RESET (%s) in tier %d"), Reason, P.ActiveTier);
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

void UStreetballDirector::Describe(const FTrackedState& S, FStreetballDirectorOutput& Out) const
{
	Out = FStreetballDirectorOutput();
	Out.State = State;
	Out.PolicyName = PolicyForState(State == EStreetballState::HardReset ? TierState : State);
	FillTask(S, Out);
}

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
	if (Clean && State != EStreetballState::JumpShot)
	{
		if (--UntilSwitch <= 0) { Hand = -Hand; ++P.HandSwitches; UntilSwitch = Rng.RandRange(2, 4); }
	}
	if (Bounce) { bPalmSince = false; bNearSince = true; }
	Out.bBounceEvent = Bounce;
	Out.bCleanBounce = Clean;
}

void UStreetballDirector::FillTask(const FTrackedState& S, FStreetballDirectorOutput& Out) const
{
	FMemory::Memzero(Out.Task);
	switch (State)
	{
	case EStreetballState::Roam:
	case EStreetballState::DribbleMoving:
	{
		const FVector2d Rel = Waypoint - FVector2d(S.PelvisPos.X, S.PelvisPos.Y);
		const double Dist = Rel.Length();
		const FVector2d Dir = S.ToHeading(Dist > 1e-6 ? Rel / Dist : FVector2d(1, 0));
		Out.Task[0] = (float)Dir.X; Out.Task[1] = (float)Dir.Y;
		Out.Task[2] = (float)FMath::Min(Dist, 10.0);
		Out.Task[3] = (float)SpeedCmd;
		if (State == EStreetballState::DribbleMoving) Out.Task[4] = (float)Hand;
		break;
	}
	case EStreetballState::DribbleStationary:
		Out.Task[0] = (float)Hand;
		Out.Task[1] = (float)ApexTarget;
		Out.Task[2] = (float)UntilSwitch;
		break;
	case EStreetballState::Scramble:
		Out.Task[0] = S.CountdownFrac;
		break;
	case EStreetballState::JumpShot:
	{
		const FVector3d Rel = S.RimPos[RimIndex] - S.PelvisPos;
		const FVector2d H = S.ToHeading(FVector2d(Rel.X, Rel.Y));
		Out.Task[0] = (float)H.X; Out.Task[1] = (float)H.Y; Out.Task[2] = (float)Rel.Z;
		Out.Task[3] = bTriggered ? 1.f : 0.f;
		Out.Task[4] = bTriggered ? (float)FMath::Max(0.0, S.Time - (ShotStartT + TriggerT)) : 0.f;
		break;
	}
	default: break;
	}
}

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
		// The world applies the reset and calls NotifyResetApplied in the same step; if it did not,
		// keep asking.
		Out.Reset.bRequested = true;
		Out.State = State; Out.PolicyName = PolicyForState(TierState);
		return;
	}
	if (S.Fallen) { RequestHardReset(TEXT("fallen"), Out); Out.State = State; Out.PolicyName = PolicyForState(TierState); return; }
	if (S.BallOutOfFence) { RequestHardReset(TEXT("ball past fence"), Out); Out.State = State; Out.PolicyName = PolicyForState(TierState); return; }

	switch (State)
	{
	case EStreetballState::Stand:
	{
		if (!bFootStartValid) { FootStart[0] = S.FootPos[0]; FootStart[1] = S.FootPos[1]; bFootStartValid = true; }
		const bool Stepped = (S.FootPos[0] - FootStart[0]).Length() > FootDriftLimit || (S.FootPos[1] - FootStart[1]).Length() > FootDriftLimit;
		if (Stepped) { P.BalanceTime = 0.0; FootStart[0] = S.FootPos[0]; FootStart[1] = S.FootPos[1]; }
		else P.BalanceTime += Dt;
		P.Progress01 = (float)FMath::Clamp(P.BalanceTime / BalanceGoalS, 0.0, 1.0);
		if (P.BalanceTime >= BalanceGoalS) { P.Mastered[0] = true; EnterTier(2, S); }
		break;
	}
	case EStreetballState::Roam:
	{
		if ((Waypoint - PelvisXY).Length() < ReachRadius) { ++P.Waypoints; NewWaypoint(S); }
		P.Progress01 = (float)FMath::Clamp((double)P.Waypoints / WaypointGoal, 0.0, 1.0);
		if (P.Waypoints >= WaypointGoal)
		{
			P.Mastered[1] = true;
			EnterTier(3, S);
			Out.Reset.bRequested = true; Out.Reset.Reason = TEXT("tier 3 start: ball to hand");
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
			EnterTier(4, S);
			Out.Reset.bRequested = true; Out.Reset.Reason = TEXT("tier 4 start");
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
	Out.PolicyName = PolicyForState(State == EStreetballState::HardReset ? TierState : State);
	FillTask(S, Out);
}
