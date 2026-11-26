#include "BroadcastCamera.h"
#include "CineCameraComponent.h"
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
		const double MinCamX = FMath::Max(15.2, Sign * Mid.X + MinBaselineDistance);
		const FVector3d Cam(Sign * MinCamX, FMath::Clamp(In.Character.Y * 0.5, -5.0, 5.0), 0.7);   // low, behind the hoop with distance guardrail
		T.Position = SimToUE(Cam);
		T.LookAt = SimToUE(FVector3d(Mid.X, Mid.Y, 1.2));
		const double Dist = FMath::Max((Mid - Cam).Length(), MinBaselineDistance);
		T.FovDeg = FMath::Clamp((float)FMath::RadiansToDegrees(2.0 * FMath::Atan2(0.5 * FMath::Max(Spread, 2.5) + 1.2, Dist)), FovMin, FovMax);
		break;
	}
	default:
	{
		// High wide shot. A fixed 62 deg lost a loose ball rolling away from the athlete: size the view from the
		// athlete-ball spread like the other shots (horizontal FOV, 16:9), with a wider cap for scrambles.
		const FVector3d Cam(FMath::Clamp(Mid.X * 0.5, -6.0, 6.0), -17.0, 9.0);
		T.Position = SimToUE(Cam);
		T.LookAt = SimToUE(FVector3d(Mid.X, Mid.Y, 0.8));
		const double Dist = (Mid - Cam).Length();
		const double Half = 0.5 * FMath::Max(Spread, 6.0) + 3.0;
		T.FovDeg = FMath::Clamp((float)FMath::RadiansToDegrees(2.0 * FMath::Atan2(Half, Dist)), FovMin, PressBoxFovMax);
		break;
	}
	}
	return T;
}

// ---------------------------------------------------------------------------- actor
ABroadcastCamera::ABroadcastCamera()
{
	PrimaryActorTick.bCanEverTick = false;
	Camera = CreateDefaultSubobject<UCineCameraComponent>(TEXT("Camera"));
	SetRootComponent(Camera);
	Camera->bConstrainAspectRatio = false;
	Camera->Filmback.SensorWidth = 36.f;
	Camera->Filmback.SensorHeight = 20.25f;
	Camera->CurrentAperture = 4.0f;
	Camera->FocusSettings.FocusMethod = ECameraFocusMethod::Manual;
	Camera->FocusSettings.ManualFocusDistance = 900.f;
	Camera->SetFieldOfView(45.f);
}

float ABroadcastCamera::GetFocusDistanceCm() const
{
	return Camera ? Camera->FocusSettings.ManualFocusDistance : 0.f;
}

void ABroadcastCamera::SetCameraMode(EStreetballCameraMode InMode)
{
	if (CameraMode == InMode) return;
	CameraMode = InMode;
	if (InMode == EStreetballCameraMode::Free)
	{
		FreePosUE = GetActorLocation();
		FreeLookAtUE = LookAt.IsNearlyZero() ? FreePosUE + GetActorForwardVector() * 400.f : LookAt;
	}
}

EStreetballCameraMode ABroadcastCamera::CycleCameraMode()
{
	const int32 Next = (static_cast<int32>(CameraMode) + 1) % 5;
	const EStreetballCameraMode Mode = static_cast<EStreetballCameraMode>(Next);
	SetCameraMode(Mode);
	return Mode;
}

void ABroadcastCamera::AddFreeOffset(const FVector& WorldDeltaUE)
{
	FreePosUE += WorldDeltaUE;
	FreeLookAtUE += WorldDeltaUE;
	if (FreePosUE.Z < 25.f)
	{
		const float Lift = 25.f - FreePosUE.Z;
		FreePosUE.Z = 25.f;
		FreeLookAtUE.Z += Lift;
	}
}

void ABroadcastCamera::UpdateCamera(const FBroadcastInputs& In, float Dt)
{
	Logic.ForcedShot = CVarForceCamera.GetValueOnGameThread();
	bool bCut = false;
	FBroadcastTarget T;

	if (CameraMode == EStreetballCameraMode::Broadcast)
	{
		bCut = Logic.Decide(In);
		T = Logic.TargetFor(Logic.Current, In);
	}
	else if (CameraMode == EStreetballCameraMode::Follow)
	{
		const FVector3d Subject = In.Character + FVector3d(0.0, 0.0, 0.9);
		T.Position = SimToUE(Subject + FVector3d(-4.2, -3.5, 1.4));
		T.LookAt = SimToUE(Subject);
		T.FovDeg = 50.f;
	}
	else if (CameraMode == EStreetballCameraMode::Orbit)
	{
		OrbitAngleRad += Dt * 0.5f;
		const FVector3d Subject = In.Character + FVector3d(0.0, 0.0, 0.9);
		const double R = 5.2;
		T.Position = SimToUE(Subject + FVector3d(FMath::Cos(OrbitAngleRad) * R, FMath::Sin(OrbitAngleRad) * R, 1.6));
		T.LookAt = SimToUE(Subject);
		T.FovDeg = 48.f;
	}
	else if (CameraMode == EStreetballCameraMode::Face)
	{
		// 1.1 m out along where the face points (she bows over the ball, so this is usually low and in front), a touch
		// to her right. The face centre sits ~9 cm out from the head bone. Never below 35 cm off the ground.
		// Yaw from where the face points (blended with the body heading, which is steadier when she bows), pitch fixed:
		// the camera sits 25 deg below the face looking up, so a bowed head still shows the face.
		const FVector2d H = In.HeadingFwd.IsNearlyZero() ? FVector2d(1.0, 0.0) : In.HeadingFwd.GetSafeNormal();
		const FVector Heading(H.X, -H.Y, 0.0);              // sim y-left -> UE y-right
		FVector Horiz = Heading * 0.6f;
		if (!In.FaceDirUE.IsNearlyZero()) Horiz += FVector(In.FaceDirUE.X, In.FaceDirUE.Y, 0.f);
		Horiz = Horiz.GetSafeNormal2D();
		if (Horiz.IsNearlyZero()) Horiz = Heading;
		const float Pitch = FMath::DegreesToRadians(25.f);
		const FVector Dir = Horiz * FMath::Cos(Pitch) - FVector::UpVector * FMath::Sin(Pitch);
		const FVector Head = In.HeadUE.IsNearlyZero() ? SimToUE(In.Character + FVector3d(0.0, 0.0, 0.7)) : In.HeadUE;
		const FVector Face = Head + Horiz * 9.f + FVector(0.f, 0.f, 4.f);
		const FVector Right = FVector::CrossProduct(FVector::UpVector, Dir).GetSafeNormal();
		T.Position = Face + Dir * 110.f + Right * 22.f;
		T.Position.Z = FMath::Max(T.Position.Z, 35.0);
		T.LookAt = Face;
		T.FovDeg = 28.f;
	}
	else
	{
		T.Position = FreePosUE.IsNearlyZero() ? GetActorLocation() : FreePosUE;
		T.Position.Z = FMath::Max(T.Position.Z, 25.0);
		T.LookAt = FreeLookAtUE.IsNearlyZero() ? SimToUE(In.Character + FVector3d(0.0, 0.0, 0.9)) : FreeLookAtUE;
		T.FovDeg = 55.f;
	}

	FVector Pos = GetActorLocation();
	float Fov = Camera->FieldOfView;
	// The face close-up sits ~1 m from her: after a reset teleport (or on entering the mode) a damped glide would pass
	// through her head, so it cuts instead.
	if (CameraMode == EStreetballCameraMode::Face && FVector::Dist(Pos, T.Position) > 60.f) bCut = true;
	if (bCut)
	{
		++CutCount;
		CutBlurSuppression = 0.25f;
		Pos = T.Position; LookAt = T.LookAt; Fov = T.FovDeg;
		PosVel = LookVel = FVector::ZeroVector; FovVel = 0.f;
	}
	else if (CameraMode == EStreetballCameraMode::Free)
	{
		Pos = T.Position; LookAt = T.LookAt; Fov = T.FovDeg;
		PosVel = LookVel = FVector::ZeroVector; FovVel = 0.f;
	}
	else
	{
		const float K = CameraMode == EStreetballCameraMode::Face ? 0.3f : 1.f;   // the close-up must keep up with her head
		Pos = FCriticalDamper::Damp(Pos, T.Position, PosVel, PositionSmoothTime * K, Dt);
		LookAt = FCriticalDamper::Damp(LookAt, T.LookAt, LookVel, LookSmoothTime * K, Dt);
		Fov = FCriticalDamper::Damp(Fov, T.FovDeg, FovVel, FovSmoothTime, Dt);
	}
	SetActorLocation(Pos);
	SetActorRotation((LookAt - Pos).Rotation());
	Camera->SetFieldOfView(Fov);

	// CineCamera manual focus pull on the athlete + brief motion-blur suppression right after a cut.
	const FVector AthleteUE = (CameraMode == EStreetballCameraMode::Face && !In.HeadUE.IsNearlyZero()) ? In.HeadUE : SimToUE(In.Character + FVector3d(0.0, 0.0, 0.9));
	Camera->FocusSettings.FocusMethod = ECameraFocusMethod::Manual;
	Camera->FocusSettings.ManualFocusDistance = FMath::Clamp((float)FVector::Dist(Pos, AthleteUE), 150.f, 6000.f);
	CutBlurSuppression = FMath::Max(0.f, CutBlurSuppression - Dt);
	Camera->PostProcessSettings.bOverride_MotionBlurAmount = CutBlurSuppression > 0.f;
	Camera->PostProcessSettings.MotionBlurAmount = CutBlurSuppression > 0.f ? 0.f : 0.3f;
}
