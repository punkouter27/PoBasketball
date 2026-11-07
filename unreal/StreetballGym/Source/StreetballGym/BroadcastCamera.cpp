#include "BroadcastCamera.h"
#include "Camera/CameraComponent.h"
#include "HAL/IConsoleManager.h"

static TAutoConsoleVariable<int32> CVarForceCamera(
	TEXT("streetball.ForceCamera"), -1,
	TEXT("Force a broadcast shot: -1 auto, 0 sideline, 1 baseline, 2 press box"), ECVF_Default);

// ---------------------------------------------------------------------------- helpers
static FVector SimToUE(const FVector3d& P) { return FVector(P.X * 100.0, -P.Y * 100.0, P.Z * 100.0); }

FVector FCriticalDamper::Damp(const FVector& Current, const FVector& Target, FVector& Velocity, float SmoothTime, float Dt)
{
	// Critically damped spring (Game Programming Gems 4 "SmoothDamp").
	SmoothTime = FMath::Max(0.0001f, SmoothTime);
	const float Omega = 2.f / SmoothTime;
	const float X = Omega * Dt;
	const float Exp = 1.f / (1.f + X + 0.48f * X * X + 0.235f * X * X * X);
	const FVector Change = Current - Target;
	const FVector Temp = (Velocity + Omega * Change) * Dt;
	Velocity = (Velocity - Omega * Temp) * Exp;
	return Target + (Change + Temp) * Exp;
}

float FCriticalDamper::Damp(float Current, float Target, float& Velocity, float SmoothTime, float Dt)
{
	SmoothTime = FMath::Max(0.0001f, SmoothTime);
	const float Omega = 2.f / SmoothTime;
	const float X = Omega * Dt;
	const float Exp = 1.f / (1.f + X + 0.48f * X * X + 0.235f * X * X * X);
	const float Change = Current - Target;
	const float Temp = (Velocity + Omega * Change) * Dt;
	Velocity = (Velocity - Omega * Temp) * Exp;
	return Target + (Change + Temp) * Exp;
}

// ---------------------------------------------------------------------------- logic
EBroadcastShot FBroadcastLogic::Desired(const FBroadcastInputs& In) const
{
	if (ForcedShot >= 0 && ForcedShot <= 2) return (EBroadcastShot)ForcedShot;
	const double DRim = FMath::Min((In.Character - In.Rim[0]).Length(), (In.Character - In.Rim[1]).Length());
	if (In.State == EStreetballState::JumpShot || DRim < BaselineDistance) return EBroadcastShot::Baseline;
	if (In.State == EStreetballState::Scramble || (In.State == EStreetballState::Roam && In.Speed > SprintSpeed)) return EBroadcastShot::PressBox;
	return EBroadcastShot::Sideline;
}

bool FBroadcastLogic::Decide(const FBroadcastInputs& In)
{
	const EBroadcastShot Want = Desired(In);
	if (bFirst) { Current = Want; LastCutTime = In.Time; bFirst = false; return true; }
	if (Want != Current && (In.Time - LastCutTime) >= CutHysteresis)
	{
		Current = Want; LastCutTime = In.Time;
		return true;
	}
	return false;
}

FBroadcastTarget FBroadcastLogic::TargetFor(EBroadcastShot Shot, const FBroadcastInputs& In) const
{
	FBroadcastTarget T;
	// Tiers 1-2 park the ball away from the athlete (3 m / off court); framing the athlete-ball midpoint
	// then pointed the camera at empty court. Only frame the ball when it is in play.
	const bool bBallInPlay = In.State != EStreetballState::Stand && In.State != EStreetballState::Roam;
	const FVector3d Ball = bBallInPlay ? In.Ball : In.Character;
	const FVector3d Mid = 0.5 * (In.Character + Ball);
	const double Spread = (In.Character - Ball).Length();
	switch (Shot)
	{
	case EBroadcastShot::Sideline:
	{
		// Dolly along the sideline, x follows the subject midpoint, clamped to the court.
		const double CamX = FMath::Clamp(Mid.X, -13.0, 13.0);
		const FVector3d Cam(CamX, SidelineY, SidelineHeight);
		T.Position = SimToUE(Cam);
		T.LookAt = SimToUE(FVector3d(Mid.X, Mid.Y, 1.0));
		const double Dist = (Mid - Cam).Length();
		const double Half = 0.5 * FMath::Max(Spread, 4.0) + 2.5;        // frame both with court context (about 46 deg at 9.3 m)
		T.FovDeg = FMath::Clamp((float)FMath::RadiansToDegrees(2.0 * FMath::Atan2(Half, Dist)), FovMin, FovMax);
		break;
	}
	case EBroadcastShot::Baseline:
	{
		const int32 Side = ((In.Character - In.Rim[0]).Length() <= (In.Character - In.Rim[1]).Length()) ? 0 : 1;
		const double Sign = (Side == 0) ? 1.0 : -1.0;
		const FVector3d Cam(Sign * 15.2, FMath::Clamp(In.Character.Y * 0.5, -5.0, 5.0), 0.7);   // low, behind the hoop
		T.Position = SimToUE(Cam);
		T.LookAt = SimToUE(FVector3d(Mid.X, Mid.Y, 1.2));
		const double Dist = (Mid - Cam).Length();
		T.FovDeg = FMath::Clamp((float)FMath::RadiansToDegrees(2.0 * FMath::Atan2(0.5 * FMath::Max(Spread, 2.5) + 1.2, Dist)), FovMin, FovMax);
		break;
	}
	default:
	{
		const FVector3d Cam(FMath::Clamp(Mid.X * 0.3, -4.0, 4.0), -17.0, 9.0);
		T.Position = SimToUE(Cam);
		T.LookAt = SimToUE(FVector3d(Mid.X, Mid.Y, 0.8));
		T.FovDeg = 62.f;
		break;
	}
	}
	return T;
}

// ---------------------------------------------------------------------------- actor
ABroadcastCamera::ABroadcastCamera()
{
	PrimaryActorTick.bCanEverTick = false;
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	SetRootComponent(Camera);
	Camera->bConstrainAspectRatio = false;
	Camera->SetFieldOfView(45.f);
}

void ABroadcastCamera::UpdateCamera(const FBroadcastInputs& In, float Dt)
{
	Logic.ForcedShot = CVarForceCamera.GetValueOnGameThread();
	const bool bCut = Logic.Decide(In);
	const FBroadcastTarget T = Logic.TargetFor(Logic.Current, In);
	FVector Pos = GetActorLocation();
	float Fov = Camera->FieldOfView;
	if (bCut)
	{
		++CutCount;
		Pos = T.Position; LookAt = T.LookAt; Fov = T.FovDeg;
		PosVel = LookVel = FVector::ZeroVector; FovVel = 0.f;
	}
	else
	{
		Pos = FCriticalDamper::Damp(Pos, T.Position, PosVel, PositionSmoothTime, Dt);
		LookAt = FCriticalDamper::Damp(LookAt, T.LookAt, LookVel, LookSmoothTime, Dt);
		Fov = FCriticalDamper::Damp(Fov, T.FovDeg, FovVel, FovSmoothTime, Dt);
	}
	SetActorLocation(Pos);
	SetActorRotation((LookAt - Pos).Rotation());
	Camera->SetFieldOfView(Fov);
}
