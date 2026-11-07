#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "StreetballTracker.generated.h"

class UMuJoCoSim;

/**
 * Physics-derived facts for one control step, in the sim frame (metres, seconds).
 * Mirrors sim/streetball/env_base.py (_update_contacts, _update_ball_state, fallen) so the
 * state machine sees exactly what the training env saw. Pure data: tests build these by hand.
 */
struct STREETBALLGYM_API FTrackedState
{
	double Time = 0.0;

	FVector3d PelvisPos = FVector3d::ZeroVector;
	FVector3d PelvisVel = FVector3d::ZeroVector;      // world linear velocity
	FVector2d HeadingFwd = FVector2d(1, 0);           // yaw-only pelvis frame (obs.py heading_mat)
	FVector2d HeadingLeft = FVector2d(0, 1);
	FVector2d FootPos[2];                              // foot_l, foot_r body xy
	FVector3d FootVel[2];                              // foot body linear velocity (world)

	FVector3d BallPos = FVector3d::ZeroVector;
	FVector3d BallVel = FVector3d::ZeroVector;

	bool FootFloor[2] = {false, false};
	bool PalmBall[2] = {false, false};                 // palm_l, palm_r touching the ball
	bool BallFloor = false;
	bool BadFloor = false;                             // any non-foot/non-palm humanoid geom on the floor
	bool BallRim = false;
	bool BallBoard = false;

	bool InControl = false;                            // env_base._update_ball_state rule
	double LooseT = -1.0;                              // sim time control was lost, -1 when in control
	float CountdownFrac = 1.0f;                        // 1 - (t - LooseT)/3, clamped; 1 when not loose
	double BadContactT = 0.0;
	bool Fallen = false;                               // pelvis z < 0.55 or BadContactT > 0.2
	bool BallOutOfFence = false;

	FVector3d RimPos[2];                               // east, west rim centres
	double FenceHalfX = 16.0, FenceHalfY = 9.5;

	FVector2d ToHeading(const FVector2d& WorldXY) const
	{
		return FVector2d(WorldXY.X * HeadingFwd.X + WorldXY.Y * HeadingFwd.Y, WorldXY.X * HeadingLeft.X + WorldXY.Y * HeadingLeft.Y);
	}
	double Speed() const { return FVector2d(PelvisVel.X, PelvisVel.Y).Length(); }
};

/** Reads a UMuJoCoSim after each control step and maintains the stateful ball/fall bookkeeping. */
UCLASS()
class STREETBALLGYM_API UStreetballTracker : public UObject
{
	GENERATED_BODY()

public:
	bool Initialize(UMuJoCoSim* InSim);

	/** Clear the stateful bookkeeping (after a reset). */
	void ResetState();

	/**
	 * Treat the ball as just-touched (used when a tier starts with the ball placed at the hand, as
	 * the training env does): control is then *lost* if the policy never touches it, which starts
	 * the scramble countdown instead of waiting forever.
	 */
	void GrantControl();

	/** Call once per control step (after the physics substeps). ControlDt is 0.02 s. */
	const FTrackedState& Update(double ControlDt);

	const FTrackedState& State() const { return S; }
	FTrackedState& MutableState() { return S; }

	/** Rule from env_base.py / obs.py, exposed for tests. */
	static bool ControlRule(const FVector3d& Ball, const FVector3d& Pelvis, double Time, double LastPalmContactT)
	{
		const double Horiz = FVector2d(Ball.X - Pelvis.X, Ball.Y - Pelvis.Y).Length();
		return Horiz < 0.75 && Ball.Z < 1.3 && (Time - LastPalmContactT) < 0.6;
	}

private:
	UPROPERTY() TObjectPtr<UMuJoCoSim> Sim = nullptr;
	FTrackedState S;
	double LastPalmContactT = -1e9;

	int32 RootQ = -1, RootV = -1, BallQ = -1, BallV = -1;
	int32 Floor = -1, BallGeom = -1, FootGeom[2] = {-1, -1}, PalmGeom[2] = {-1, -1}, FootBody[2] = {-1, -1};
	TArray<bool> BadFloorMask;     // per geom: humanoid geom that is not a foot or palm
	TArray<bool> RimMask, BoardMask;
};
