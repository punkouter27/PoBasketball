#pragma once

#include "CoreMinimal.h"
#include "StreetballDirector.h"
#include "StreetballTracker.h"

/**
 * Cosmetic game events derived from the director/tracker (read only). They drive voice lines, crowd audio, grunts,
 * VFX and the net swish. Nothing here writes to the sim: the presentation layer is a pure listener (contract §5).
 */
enum class EPresentationEvent : uint8
{
	Make,
	Swish,          // make with no rim contact since the shot started (also fires Make)
	Miss,
	RimOut,         // miss that touched the rim (also fires Miss)
	ScrambleStart,
	ScrambleSave,
	Fall,
	TierUp,
	Crossover,
	Idle,
	Jump,           // pelvis leaves the ground fast (grunt)
	Count
};

struct STREETBALLGYM_API FPresentationEventDetector
{
	static const TCHAR* Name(EPresentationEvent E);
	/** voice_bank.json event key ("make", "rim_out", ...), or nullptr when the event has no lines (Jump). */
	static const TCHAR* VoiceKey(EPresentationEvent E);

	void Reset();

	/**
	 * One control step, after UStreetballDirector::Update. Appends to Out (does not clear it; caller reserves).
	 * Reset spec reasons are compared as text, so the director's reason literals are part of this contract.
	 */
	void Update(const FTrackedState& S, const FStreetballDirectorOutput& Dir, const FStreetballProgress& P, EStreetballState State, TArray<EPresentationEvent>& Out);

	/** Notify that something was said/played, so Idle waits again. */
	void MarkActivity(double Time) { LastActivityT = Time; }

	double IdleAfterS = 22.0;
	double JumpVz = 1.1;               // m/s upward pelvis velocity that counts as a jump

private:
	bool bValid = false;
	EStreetballState PrevState = EStreetballState::Stand;
	int32 PrevTier = 1;
	int32 PrevMastered = 0;
	int32 PrevShotsTaken = 0, PrevShotsMade = 0;
	int32 PrevSwitches = 0;
	bool bRimSinceShot = false;
	bool bAirborne = false;
	double LastActivityT = 0.0;
};
