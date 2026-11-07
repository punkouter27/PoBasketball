#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "SimClock.generated.h"

class UMuJoCoSim;

/** Snapshot of every body pose in UE space, taken after a physics step, for render interpolation. */
struct FSimPoseSnapshot
{
	TArray<FVector> Pos;     // cm
	TArray<FQuat> Rot;       // UE quats
	double SimTime = 0.0;
};

DECLARE_DELEGATE_OneParam(FOnControlStep, UMuJoCoSim* /*Sim*/);
DECLARE_DELEGATE_OneParam(FOnPhysicsStep, UMuJoCoSim* /*Sim*/);   // after every mj_step (contact sampling)

/**
 * Blueprint B.5 / plan B4: fixed-step accumulator.
 *
 *  - Physics advances in exact multiples of the model timestep (0.002 s). The frame delta never
 *    reaches the integrator, so the trajectory is a pure function of the number of steps taken.
 *  - Every SubstepsPerControl physics steps the control delegate runs (policy at 50 Hz).
 *  - The last two post-step snapshots are kept; Alpha = Accumulator / dt gives the render blend.
 *  - Frame deltas above MaxFrameDelta are clamped (slow frames slow the sim down rather than
 *    letting it run away); this is the only situation in which wall-clock affects the result.
 */
UCLASS(BlueprintType)
class STREETBALLGYM_API USimClock : public UObject
{
	GENERATED_BODY()

public:
	void Initialize(UMuJoCoSim* InSim, int32 InSubstepsPerControl = 10);

	/** Advance by a frame of wall-clock time. Returns the number of physics steps taken. */
	int32 Advance(double DeltaSeconds);

	/** Interpolation factor in [0,1) between Prev and Curr snapshots for this frame. */
	double GetAlpha() const;

	const FSimPoseSnapshot& Prev() const { return Snapshots[PrevIdx]; }
	const FSimPoseSnapshot& Curr() const { return Snapshots[1 - PrevIdx]; }

	/** Refill both snapshots from the current sim state (after a teleport/reset, so no blend across it). */
	void Resnapshot() { TakeSnapshot(Snapshots[0]); TakeSnapshot(Snapshots[1]); }

	/** Interpolated UE transform of a body for rendering. */
	FTransform GetInterpolatedBody(int32 BodyId) const;

	int64 GetStepCount() const { return StepCount; }
	int64 GetControlCount() const { return ControlCount; }
	int32 GetSubstepsPerControl() const { return SubstepsPerControl; }
	double GetTimestep() const { return Timestep; }
	UMuJoCoSim* GetSim() const { return Sim; }

	FOnControlStep OnControlStep;
	FOnPhysicsStep OnPhysicsStep;

	/** Upper bound on simulated time per frame (seconds). */
	double MaxFrameDelta = 0.1;

private:
	void TakeSnapshot(FSimPoseSnapshot& Out) const;

	UPROPERTY() TObjectPtr<UMuJoCoSim> Sim = nullptr;
	FSimPoseSnapshot Snapshots[2];
	int32 PrevIdx = 0;
	double Accumulator = 0.0;
	double Timestep = 0.002;
	int32 SubstepsPerControl = 10;
	int32 SubstepInControl = 0;
	int64 StepCount = 0;
	int64 ControlCount = 0;
};
