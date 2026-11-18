#pragma once

#include "CoreMinimal.h"

class UMuJoCoSim;

/**
 * C++ twin of sim/streetball/obs.py (NumObs-float observation, NumAction-float action rule).
 * Index tables come from Content/Sim/obs_spec.json so both sides share one definition.
 * Verified slot-for-slot against shared/golden/obs_golden.npz by the Streetball.ObsGolden test.
 */
struct STREETBALLGYM_API FObsBuilder
{
	static constexpr int32 NumJoints = 29;
	static constexpr int32 NumAction = 29;
	static constexpr int32 NumTask = 12;
	static constexpr int32 NumBase = 26 + 3 * NumJoints; // 113
	static constexpr int32 NumObs = NumBase + NumTask;   // 125
	static_assert(NumBase == 113 && NumObs == 125, "ObsBuilder dimensions must match obs_spec.json");

	// Slot offsets (obs_spec.json "slots"), derived from NumJoints so callers never hard-code them.
	// Initialize() checks them against the spec file.
	static constexpr int32 SlotJointPos = 9;
	static constexpr int32 SlotJointVel = SlotJointPos + NumJoints;
	static constexpr int32 SlotPrevAction = SlotJointVel + NumJoints;
	static constexpr int32 SlotBall = SlotPrevAction + NumJoints;      // ball_pos_rel[3], ball_vel_rel[3]
	static constexpr int32 SlotInControl = SlotBall + 6;
	static constexpr int32 SlotPalmBallDist = SlotBall + 7;          // [2] left, right
	static constexpr int32 SlotFootContact = SlotBall + 9;           // [2] left, right
	static constexpr int32 SlotPelvisHeight = SlotBall + 11;
	static constexpr int32 SlotTask = NumBase;
	static_assert(SlotBall + 17 == NumBase, "base block ends with countdown_frac + reserved");

	bool Initialize(UMuJoCoSim* Sim, const FString& ObsSpecJsonPath);
	bool IsInitialized() const { return bInit; }

	/** mj_forward must be current. Writes exactly NumObs floats. */
	void Compute(const UMuJoCoSim* Sim, TConstArrayView<float> PrevAction, TConstArrayView<float> Task,
	             float InControl, float CountdownFrac, TArray<float>& Out) const;

	/** ctrl = clip(nominal + a * 0.5*(hi-lo), lo, hi) */
	void ActionToCtrl(TConstArrayView<float> Action, TArray<float>& OutCtrl) const;

	/** Append zero-initialized inputs after the frozen contract without reordering existing slots. */
	static void AppendZeroInitInputs(TArray<float>& Out, int32 ExtraCount);

	TArray<FString> JointOrder;
	TArray<int32> QAdr, VAdr;
	TArray<double> Nominal, Lo, Hi, Half;
	int32 RootQ = -1, RootV = -1, BallQ = -1, BallV = -1;
	int32 PalmL = -1, PalmR = -1, FootL = -1, FootR = -1, ToeL = -1, ToeR = -1, Floor = -1;

private:
	bool bInit = false;
};
