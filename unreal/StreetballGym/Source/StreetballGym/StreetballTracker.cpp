#include "StreetballTracker.h"
#include "MuJoCoSim.h"
#include "StreetballGym.h"

bool UStreetballTracker::Initialize(UMuJoCoSim* InSim)
{
	Sim = InSim;
	if (!Sim || !Sim->IsLoaded()) return false;
	const mjModel* M = Sim->GetModel();
	const int32 RootJ = Sim->JointId(TEXT("root")), BallJ = Sim->JointId(TEXT("ball"));
	RootQ = M->jnt_qposadr[RootJ]; RootV = M->jnt_dofadr[RootJ];
	BallQ = M->jnt_qposadr[BallJ]; BallV = M->jnt_dofadr[BallJ];
	Floor = Sim->GeomId(TEXT("floor"));
	BallGeom = Sim->GeomId(TEXT("ball"));
	FootGeom[0] = Sim->GeomId(TEXT("foot_l")); FootGeom[1] = Sim->GeomId(TEXT("foot_r"));
	PalmGeom[0] = Sim->GeomId(TEXT("palm_l")); PalmGeom[1] = Sim->GeomId(TEXT("palm_r"));
	FootBody[0] = Sim->BodyId(TEXT("foot_l")); FootBody[1] = Sim->BodyId(TEXT("foot_r"));

	// humanoid geoms = geoms on bodies in the pelvis subtree
	const int32 Pelvis = Sim->BodyId(TEXT("pelvis"));
	TArray<bool> InSubtree; InSubtree.SetNumZeroed(M->nbody);
	for (int32 b = 0; b < M->nbody; ++b)
	{
		int32 c = b;
		while (c > 0) { if (c == Pelvis) { InSubtree[b] = true; break; } c = M->body_parentid[c]; }
	}
	BadFloorMask.SetNumZeroed(M->ngeom); RimMask.SetNumZeroed(M->ngeom); BoardMask.SetNumZeroed(M->ngeom);
	for (int32 g = 0; g < M->ngeom; ++g)
	{
		const bool Hum = InSubtree[M->geom_bodyid[g]];
		BadFloorMask[g] = Hum && g != FootGeom[0] && g != FootGeom[1] && g != PalmGeom[0] && g != PalmGeom[1];
		const FString N = Sim->GeomName(g);
		RimMask[g] = N.StartsWith(TEXT("rim_")) && !N.StartsWith(TEXT("rim_bracket"));
		BoardMask[g] = N.StartsWith(TEXT("board_"));
	}
	for (int32 i = 0; i < 2; ++i)
	{
		const int32 Site = Sim->SiteId(i == 0 ? TEXT("rim_center_e") : TEXT("rim_center_w"));
		const double* P = M->site_pos + 3 * Site;    // static body: model-space == world-space
		S.RimPos[i] = FVector3d(P[0], P[1], P[2]);
	}
	ResetState();
	return Floor >= 0 && BallGeom >= 0 && FootGeom[0] >= 0 && PalmGeom[0] >= 0;
}

void UStreetballTracker::ResetState()
{
	LastPalmContactT = -1e9;
	S.LooseT = -1.0;
	S.CountdownFrac = 1.0f;
	S.InControl = false;
	S.BadContactT = 0.0;
	S.Fallen = false;
	S.BallOutOfFence = false;
	if (Sim && Sim->IsLoaded()) Update(0.0);
}

void UStreetballTracker::GrantControl()
{
	LastPalmContactT = S.Time;
	S.InControl = ControlRule(S.BallPos, S.PelvisPos, S.Time, LastPalmContactT);
	S.LooseT = -1.0;
	S.CountdownFrac = 1.0f;
}

const FTrackedState& UStreetballTracker::Update(double ControlDt)
{
	const mjModel* M = Sim->GetModel();
	const mjData* D = Sim->GetData();
	S.Time = D->time;

	const double* Q = D->qpos + RootQ;
	S.PelvisPos = FVector3d(Q[0], Q[1], Q[2]);
	S.PelvisVel = FVector3d(D->qvel[RootV], D->qvel[RootV + 1], D->qvel[RootV + 2]);
	{
		// heading frame from the pelvis quaternion (w,x,y,z): first column of R with z zeroed
		const double w = Q[3], x = Q[4], y = Q[5], z = Q[6];
		double fx = 1 - 2 * (y * y + z * z), fy = 2 * (x * y + w * z);
		const double n = FMath::Sqrt(fx * fx + fy * fy);
		if (n < 1e-6) { fx = 1; fy = 0; } else { fx /= n; fy /= n; }
		S.HeadingFwd = FVector2d(fx, fy);
		S.HeadingLeft = FVector2d(-fy, fx);
	}
	for (int32 i = 0; i < 2; ++i)
	{
		const double* P = D->xpos + 3 * FootBody[i];
		S.FootPos[i] = FVector2d(P[0], P[1]);
		S.FootVel[i] = Sim->GetBodyLinearVelocitySim(FootBody[i]);
	}
	const double* B = D->qpos + BallQ;
	S.BallPos = FVector3d(B[0], B[1], B[2]);
	S.BallVel = FVector3d(D->qvel[BallV], D->qvel[BallV + 1], D->qvel[BallV + 2]);

	// contacts (sampled at the control step, as the training env does)
	S.FootFloor[0] = S.FootFloor[1] = S.PalmBall[0] = S.PalmBall[1] = false;
	S.BallFloor = S.BadFloor = S.BallRim = S.BallBoard = false;
	for (int32 c = 0; c < D->ncon; ++c)
	{
		const int32 g0 = D->contact[c].geom[0], g1 = D->contact[c].geom[1];
		if (g0 == Floor || g1 == Floor)
		{
			const int32 Other = (g0 == Floor) ? g1 : g0;
			if (Other == FootGeom[0]) S.FootFloor[0] = true;
			else if (Other == FootGeom[1]) S.FootFloor[1] = true;
			else if (Other == BallGeom) S.BallFloor = true;
			if (BadFloorMask.IsValidIndex(Other) && BadFloorMask[Other]) S.BadFloor = true;
		}
		if (g0 == BallGeom || g1 == BallGeom)
		{
			const int32 Other = (g0 == BallGeom) ? g1 : g0;
			if (Other == PalmGeom[0]) S.PalmBall[0] = true;
			else if (Other == PalmGeom[1]) S.PalmBall[1] = true;
			else if (RimMask.IsValidIndex(Other) && RimMask[Other]) S.BallRim = true;
			else if (BoardMask.IsValidIndex(Other) && BoardMask[Other]) S.BallBoard = true;
		}
	}

	// ball control / loose / countdown (env_base._update_ball_state)
	if (S.PalmBall[0] || S.PalmBall[1]) LastPalmContactT = S.Time;
	const bool Ctrl = ControlRule(S.BallPos, S.PelvisPos, S.Time, LastPalmContactT);
	const bool NewlyLoose = !Ctrl && S.InControl;
	if (NewlyLoose) S.LooseT = S.Time;
	if (Ctrl) S.LooseT = -1.0;
	S.InControl = Ctrl;
	S.CountdownFrac = (S.LooseT >= 0.0) ? (float)FMath::Clamp(1.0 - (S.Time - S.LooseT) / 3.0, 0.0, 1.0) : 1.0f;

	// fallen
	S.BadContactT = S.BadFloor ? S.BadContactT + ControlDt : 0.0;
	S.Fallen = S.PelvisPos.Z < 0.55 || S.BadContactT > 0.2;
	S.BallOutOfFence = FMath::Abs(S.BallPos.X) > S.FenceHalfX || FMath::Abs(S.BallPos.Y) > S.FenceHalfY;
	return S;
}
