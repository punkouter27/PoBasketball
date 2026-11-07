#include "SimClock.h"
#include "MuJoCoSim.h"

void USimClock::Initialize(UMuJoCoSim* InSim, int32 InSubstepsPerControl)
{
	Sim = InSim;
	SubstepsPerControl = FMath::Max(1, InSubstepsPerControl);
	Timestep = Sim ? (double)Sim->GetTimestep() : 0.002;
	Accumulator = 0.0;
	SubstepInControl = 0;
	StepCount = 0;
	ControlCount = 0;
	PrevIdx = 0;
	TakeSnapshot(Snapshots[0]);
	TakeSnapshot(Snapshots[1]);
}

int32 USimClock::Advance(double DeltaSeconds)
{
	if (!Sim || !Sim->IsLoaded()) return 0;
	Accumulator += FMath::Clamp(DeltaSeconds, 0.0, MaxFrameDelta);
	int32 Steps = 0;
	while (Accumulator >= Timestep)
	{
		if (SubstepInControl == 0)
		{
			OnControlStep.ExecuteIfBound(Sim);
			++ControlCount;
		}
		Sim->Step(1);
		++StepCount;
		OnPhysicsStep.ExecuteIfBound(Sim);
		SubstepInControl = (SubstepInControl + 1) % SubstepsPerControl;
		Accumulator -= Timestep;
		++Steps;
		// Rotate snapshots after every physics step so Prev is always exactly one step older
		// than Curr (continuous interpolation regardless of how many steps a frame took).
		TakeSnapshot(Snapshots[PrevIdx]);
		PrevIdx = 1 - PrevIdx;
	}
	return Steps;
}

double USimClock::GetAlpha() const
{
	return FMath::Clamp(Accumulator / Timestep, 0.0, 1.0);
}

void USimClock::TakeSnapshot(FSimPoseSnapshot& Out) const
{
	if (!Sim || !Sim->IsLoaded()) return;
	const int32 N = Sim->NumBodies();
	Out.Pos.SetNum(N);
	Out.Rot.SetNum(N);
	for (int32 b = 0; b < N; ++b)
	{
		const FTransform T = Sim->GetBodyTransformUE(b);
		Out.Pos[b] = T.GetLocation();
		Out.Rot[b] = T.GetRotation();
	}
	Out.SimTime = Sim->GetSimTime();
}

FTransform USimClock::GetInterpolatedBody(int32 BodyId) const
{
	const FSimPoseSnapshot& A = Prev();
	const FSimPoseSnapshot& B = Curr();
	if (!A.Pos.IsValidIndex(BodyId) || !B.Pos.IsValidIndex(BodyId)) return FTransform::Identity;
	const double Alpha = GetAlpha();
	return FTransform(FQuat::Slerp(A.Rot[BodyId], B.Rot[BodyId], Alpha), FMath::Lerp(A.Pos[BodyId], B.Pos[BodyId], Alpha));
}
