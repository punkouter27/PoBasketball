#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StreetballDirector.h"
#include "BroadcastCamera.generated.h"

class UCameraComponent;

UENUM(BlueprintType)
enum class EBroadcastShot : uint8
{
	Sideline,
	Baseline,
	PressBox
};

/** Inputs the cut logic needs each frame (sim metres). */
struct STREETBALLGYM_API FBroadcastInputs
{
	double Time = 0.0;
	FVector3d Character = FVector3d::ZeroVector;
	FVector3d Ball = FVector3d::ZeroVector;
	double Speed = 0.0;                     // horizontal character speed m/s
	EStreetballState State = EStreetballState::Stand;
	FVector3d Rim[2];                       // east, west
};

/** Where the camera should be for a shot (UE cm). */
struct STREETBALLGYM_API FBroadcastTarget
{
	FVector Position = FVector::ZeroVector;
	FVector LookAt = FVector::ZeroVector;
	float FovDeg = 45.f;
};

/**
 * PRD 3.1 cut rules + framing, free of engine objects so tests can drive it:
 *   Baseline  : character within BaselineDistance of a rim, or JUMP_SHOT.
 *   PressBox  : ROAM with speed > SprintSpeed, or SCRAMBLE.
 *   Sideline  : otherwise (dolly on y = SidelineY, keeps character + ball in frame).
 * A cut happens only if the desired shot differs and at least CutHysteresis seconds passed.
 */
struct STREETBALLGYM_API FBroadcastLogic
{
	double SidelineY = -9.3;        // sim metres (court side), 2 m outside the sideline
	double SidelineHeight = 2.2;
	double BaselineDistance = 6.0;
	double SprintSpeed = 2.0;
	double CutHysteresis = 2.0;
	float FovMin = 22.f, FovMax = 60.f;
	int32 ForcedShot = -1;          // -1 auto; else EBroadcastShot

	EBroadcastShot Current = EBroadcastShot::Sideline;
	double LastCutTime = -1e9;
	bool bFirst = true;

	EBroadcastShot Desired(const FBroadcastInputs& In) const;
	/** Applies hysteresis; returns true when a cut happened this call. */
	bool Decide(const FBroadcastInputs& In);
	FBroadcastTarget TargetFor(EBroadcastShot Shot, const FBroadcastInputs& In) const;
};

/** Critically damped tracking of a scalar/vector (Unity-style SmoothDamp). */
struct STREETBALLGYM_API FCriticalDamper
{
	static FVector Damp(const FVector& Current, const FVector& Target, FVector& Velocity, float SmoothTime, float Dt);
	static float Damp(float Current, float Target, float& Velocity, float SmoothTime, float Dt);
};

/** The one camera actor (pre-allocated by the world). */
UCLASS()
class STREETBALLGYM_API ABroadcastCamera : public AActor
{
	GENERATED_BODY()

public:
	ABroadcastCamera();

	/** Drive the camera for this frame. */
	void UpdateCamera(const FBroadcastInputs& In, float Dt);

	FBroadcastLogic Logic;
	float PositionSmoothTime = 0.45f;
	float LookSmoothTime = 0.25f;
	float FovSmoothTime = 0.6f;

	UPROPERTY(VisibleAnywhere) TObjectPtr<UCameraComponent> Camera;
	EBroadcastShot GetShot() const { return Logic.Current; }
	int32 GetCutCount() const { return CutCount; }

private:
	FVector PosVel = FVector::ZeroVector, LookVel = FVector::ZeroVector;
	float FovVel = 0.f;
	FVector LookAt = FVector::ZeroVector;
	int32 CutCount = 0;
};
