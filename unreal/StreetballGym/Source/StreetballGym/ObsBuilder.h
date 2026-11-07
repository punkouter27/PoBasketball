#pragma once

#include "CoreMinimal.h"

class UMuJoCoSim;

/**
 * C++ twin of sim/streetball/obs.py (119-float observation, 27-float action rule).
 * Index tables come from Content/Sim/obs_spec.json so both sides share one definition.
 * Verified slot-for-slot against shared/golden/obs_golden.npz by the Streetball.ObsGolden test.
 */
struct STREETBALLGYM_API FObsBuilder
{
	static constexpr int32 NumJoints = 27;
	static constexpr int32 NumAction = 27;
	static constexpr int32 NumTask = 12;
	static constexpr int32 NumBase = 107;
	static constexpr int32 NumObs = NumBase + NumTask;

	bool Initialize(UMuJoCoSim* Sim, const FString& ObsSpecJsonPath);
	bool IsInitialized() const { return bInit; }

	/** mj_forward must be current. Writes exactly NumObs floats. */
	void Compute(const UMuJoCoSim* Sim, TConstArrayView<float> PrevAction, TConstArrayView<float> Task,
	             float InControl, float CountdownFrac, TArray<float>& Out) const;

	/** ctrl = clip(nominal + a * 0.5*(hi-lo), lo, hi) */
	void ActionToCtrl(TConstArrayView<float> Action, TArray<float>& OutCtrl) const;

	TArray<FString> JointOrder;
	TArray<int32> QAdr, VAdr;
	TArray<double> Nominal, Lo, Hi, Half;
	int32 RootQ = -1, RootV = -1, BallQ = -1, BallV = -1;
	int32 PalmL = -1, PalmR = -1, FootL = -1, FootR = -1, Floor = -1;

private:
	bool bInit = false;
};
