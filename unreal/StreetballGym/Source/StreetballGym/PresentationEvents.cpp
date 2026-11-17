#include "PresentationEvents.h"

const TCHAR* FPresentationEventDetector::Name(EPresentationEvent E)
{
	switch (E)
	{
	case EPresentationEvent::Make: return TEXT("make");
	case EPresentationEvent::Swish: return TEXT("swish");
	case EPresentationEvent::Miss: return TEXT("miss");
	case EPresentationEvent::RimOut: return TEXT("rim_out");
	case EPresentationEvent::ScrambleStart: return TEXT("scramble_start");
	case EPresentationEvent::ScrambleSave: return TEXT("scramble_save");
	case EPresentationEvent::Fall: return TEXT("fall");
	case EPresentationEvent::TierUp: return TEXT("tier_up");
	case EPresentationEvent::Crossover: return TEXT("crossover");
	case EPresentationEvent::Idle: return TEXT("idle");
	case EPresentationEvent::Jump: return TEXT("jump");
	default: return TEXT("?");
	}
}

const TCHAR* FPresentationEventDetector::VoiceKey(EPresentationEvent E)
{
	return E == EPresentationEvent::Jump ? nullptr : Name(E);
}

void FPresentationEventDetector::Reset()
{
	bValid = false;
}

void FPresentationEventDetector::Update(const FTrackedState& S, const FStreetballDirectorOutput& Dir, const FStreetballProgress& P,
	EStreetballState State, TArray<EPresentationEvent>& Out)
{
	int32 Mastered = 0;
	for (bool b : P.Mastered) Mastered += b ? 1 : 0;
	if (!bValid)
	{
		bValid = true;
		PrevState = State; PrevTier = P.ActiveTier; PrevMastered = Mastered;
		PrevShotsTaken = P.ShotsTaken; PrevShotsMade = P.ShotsMade; PrevSwitches = P.HandSwitches;
		bRimSinceShot = false; bAirborne = false; LastActivityT = S.Time;
		return;
	}

	const int32 Before = Out.Num();
	if (S.BallRim) bRimSinceShot = true;

	// shots (tier 5): the director counts a resolved shot in the same step it orders the shot reset
	if (P.ShotsTaken > PrevShotsTaken || (P.ShotsTaken < PrevShotsTaken && P.ShotsTaken == 0))
	{
		if (P.ShotsMade > PrevShotsMade)
		{
			Out.Add(EPresentationEvent::Make);
			if (!bRimSinceShot) Out.Add(EPresentationEvent::Swish);
		}
		else
		{
			Out.Add(EPresentationEvent::Miss);
			if (bRimSinceShot) Out.Add(EPresentationEvent::RimOut);
		}
		bRimSinceShot = false;
	}
	else if (Dir.bScoreEvent && P.ActiveTier != 5)
	{
		Out.Add(EPresentationEvent::Make);
	}
	if (State == EStreetballState::JumpShot && PrevState != EStreetballState::JumpShot) bRimSinceShot = false;

	// scramble
	if (State == EStreetballState::Scramble && PrevState != EStreetballState::Scramble) Out.Add(EPresentationEvent::ScrambleStart);
	if (PrevState == EStreetballState::Scramble && State != EStreetballState::Scramble && !Dir.Reset.bRequested
		&& State != EStreetballState::HardReset)
	{
		Out.Add(EPresentationEvent::ScrambleSave);
	}

	// falls (the director's reason literal)
	if (Dir.Reset.bRequested && Dir.Reset.Reason && FCString::Strcmp(Dir.Reset.Reason, TEXT("fallen")) == 0) Out.Add(EPresentationEvent::Fall);

	// tier progress
	if (Mastered > PrevMastered || P.ActiveTier > PrevTier) Out.Add(EPresentationEvent::TierUp);

	// commanded hand switches
	if (P.HandSwitches > PrevSwitches) Out.Add(EPresentationEvent::Crossover);

	// jumps: rising edge of a fast upward pelvis with both feet off the floor
	const bool bUp = S.PelvisVel.Z > JumpVz && !S.FootFloor[0] && !S.FootFloor[1];
	if (bUp && !bAirborne) Out.Add(EPresentationEvent::Jump);
	bAirborne = bUp || (bAirborne && !(S.FootFloor[0] || S.FootFloor[1]));

	// idle chatter while dribbling
	const bool bDribbling = State == EStreetballState::DribbleStationary || State == EStreetballState::DribbleMoving;
	if (Out.Num() > Before) LastActivityT = S.Time;
	else if (bDribbling && S.Time - LastActivityT > IdleAfterS) { Out.Add(EPresentationEvent::Idle); LastActivityT = S.Time; }

	PrevState = State; PrevTier = P.ActiveTier; PrevMastered = Mastered;
	PrevShotsTaken = P.ShotsTaken; PrevShotsMade = P.ShotsMade; PrevSwitches = P.HandSwitches;
}
