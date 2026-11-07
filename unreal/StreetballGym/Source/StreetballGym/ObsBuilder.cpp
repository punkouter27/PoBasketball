#include "ObsBuilder.h"
#include "MuJoCoSim.h"
#include "StreetballGym.h"
#include "Misc/FileHelper.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	// MuJoCo (w,x,y,z) -> rotation matrix (world <- body), row-major, same formula as obs.py
	void QuatToMat(const double* Q, double R[3][3])
	{
		const double w = Q[0], x = Q[1], y = Q[2], z = Q[3];
		R[0][0] = 1 - 2 * (y * y + z * z); R[0][1] = 2 * (x * y - w * z);     R[0][2] = 2 * (x * z + w * y);
		R[1][0] = 2 * (x * y + w * z);     R[1][1] = 1 - 2 * (x * x + z * z); R[1][2] = 2 * (y * z - w * x);
		R[2][0] = 2 * (x * z - w * y);     R[2][1] = 2 * (y * z + w * x);     R[2][2] = 1 - 2 * (x * x + y * y);
	}
	// out = R^T v
	void MulT(const double R[3][3], const double* V, double* Out)
	{
		for (int i = 0; i < 3; ++i) Out[i] = R[0][i] * V[0] + R[1][i] * V[1] + R[2][i] * V[2];
	}
	void HeadingMat(const double R[3][3], double H[3][3])
	{
		double fx = R[0][0], fy = R[1][0];                 // R[:,0] with z zeroed
		const double n = FMath::Sqrt(fx * fx + fy * fy);
		if (n < 1e-6) { fx = 1.0; fy = 0.0; } else { fx /= n; fy /= n; }
		// columns: fwd, left, up
		H[0][0] = fx;  H[0][1] = -fy; H[0][2] = 0.0;
		H[1][0] = fy;  H[1][1] = fx;  H[1][2] = 0.0;
		H[2][0] = 0.0; H[2][1] = 0.0; H[2][2] = 1.0;
	}
}

bool FObsBuilder::Initialize(UMuJoCoSim* Sim, const FString& SpecPath)
{
	bInit = false;
	if (!Sim || !Sim->IsLoaded()) return false;
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *SpecPath))
	{
		UE_LOG(LogStreetball, Error, TEXT("ObsBuilder: cannot read %s"), *SpecPath);
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Root) || !Root.IsValid()) return false;

	JointOrder.Reset(); QAdr.Reset(); VAdr.Reset(); Nominal.Reset(); Lo.Reset(); Hi.Reset(); Half.Reset();
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("joint_order"))) JointOrder.Add(V->AsString());
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("nominal_rad"))) Nominal.Add(V->AsNumber());
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("lo_rad"))) Lo.Add(V->AsNumber());
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("hi_rad"))) Hi.Add(V->AsNumber());
	if (JointOrder.Num() != NumJoints || Nominal.Num() != NumJoints || Lo.Num() != NumJoints || Hi.Num() != NumJoints)
	{
		UE_LOG(LogStreetball, Error, TEXT("ObsBuilder: spec has %d joints, expected %d"), JointOrder.Num(), NumJoints);
		return false;
	}
	const mjModel* M = Sim->GetModel();
	for (int32 i = 0; i < NumJoints; ++i)
	{
		const int32 J = Sim->JointId(JointOrder[i]);
		if (J < 0) { UE_LOG(LogStreetball, Error, TEXT("ObsBuilder: joint %s missing"), *JointOrder[i]); return false; }
		QAdr.Add(M->jnt_qposadr[J]);
		VAdr.Add(M->jnt_dofadr[J]);
		Half.Add(0.5 * (Hi[i] - Lo[i]));
		// Actuator i must drive joint i (obs.py asserts the same).
		if (Sim->ActuatorId(JointOrder[i]) != i) { UE_LOG(LogStreetball, Error, TEXT("ObsBuilder: actuator order mismatch at %s"), *JointOrder[i]); return false; }
	}
	const int32 RootJ = Sim->JointId(TEXT("root"));
	const int32 BallJ = Sim->JointId(TEXT("ball"));
	RootQ = M->jnt_qposadr[RootJ]; RootV = M->jnt_dofadr[RootJ];
	BallQ = M->jnt_qposadr[BallJ]; BallV = M->jnt_dofadr[BallJ];
	PalmL = Sim->SiteId(TEXT("palm_l")); PalmR = Sim->SiteId(TEXT("palm_r"));
	FootL = Sim->GeomId(TEXT("foot_l")); FootR = Sim->GeomId(TEXT("foot_r"));
	Floor = Sim->GeomId(TEXT("floor"));
	bInit = RootQ >= 0 && BallQ >= 0 && PalmL >= 0 && PalmR >= 0 && FootL >= 0 && FootR >= 0 && Floor >= 0;
	return bInit;
}

void FObsBuilder::Compute(const UMuJoCoSim* Sim, TConstArrayView<float> PrevAction, TConstArrayView<float> Task,
                          float InControl, float CountdownFrac, TArray<float>& Out) const
{
	Out.SetNumZeroed(NumObs);
	if (!bInit || !Sim || !Sim->IsLoaded()) return;
	const mjData* D = Sim->GetData();

	double R[3][3], H[3][3], Tmp[3];
	QuatToMat(D->qpos + RootQ + 3, R);
	HeadingMat(R, H);
	const double* PPelvis = D->qpos + RootQ;
	const double* VPelvis = D->qvel + RootV;
	const double* WPelvis = D->qvel + RootV + 3;

	const double G[3] = {0.0, 0.0, -1.0};
	MulT(R, G, Tmp);       for (int i = 0; i < 3; ++i) Out[0 + i] = (float)Tmp[i];
	MulT(R, VPelvis, Tmp); for (int i = 0; i < 3; ++i) Out[3 + i] = (float)Tmp[i];
	for (int i = 0; i < 3; ++i) Out[6 + i] = (float)(0.25 * WPelvis[i]);
	for (int i = 0; i < NumJoints; ++i)
	{
		Out[9 + i] = (float)(D->qpos[QAdr[i]] - Nominal[i]);
		Out[36 + i] = (float)(0.1 * D->qvel[VAdr[i]]);
		Out[63 + i] = PrevAction.IsValidIndex(i) ? PrevAction[i] : 0.f;
	}
	const double* PBall = D->qpos + BallQ;
	const double* VBall = D->qvel + BallV;
	const double* WBall = D->qvel + BallV + 3;
	double Rel[3];
	for (int i = 0; i < 3; ++i) Rel[i] = PBall[i] - PPelvis[i];
	MulT(H, Rel, Tmp); for (int i = 0; i < 3; ++i) Out[90 + i] = (float)Tmp[i];
	for (int i = 0; i < 3; ++i) Rel[i] = VBall[i] - VPelvis[i];
	MulT(H, Rel, Tmp); for (int i = 0; i < 3; ++i) Out[93 + i] = (float)(0.5 * Tmp[i]);
	Out[96] = InControl;
	const double* SL = D->site_xpos + 3 * PalmL;
	const double* SR = D->site_xpos + 3 * PalmR;
	Out[97] = (float)FMath::Sqrt(FMath::Square(SL[0] - PBall[0]) + FMath::Square(SL[1] - PBall[1]) + FMath::Square(SL[2] - PBall[2]));
	Out[98] = (float)FMath::Sqrt(FMath::Square(SR[0] - PBall[0]) + FMath::Square(SR[1] - PBall[1]) + FMath::Square(SR[2] - PBall[2]));
	float FL = 0.f, FR = 0.f;
	for (int c = 0; c < D->ncon; ++c)
	{
		const int g1 = D->contact[c].geom[0], g2 = D->contact[c].geom[1];
		if (g1 == Floor || g2 == Floor)
		{
			const int Other = (g1 == Floor) ? g2 : g1;
			if (Other == FootL) FL = 1.f; else if (Other == FootR) FR = 1.f;
		}
	}
	Out[99] = FL; Out[100] = FR;
	Out[101] = (float)PPelvis[2];
	MulT(H, WBall, Tmp); for (int i = 0; i < 3; ++i) Out[102 + i] = (float)(0.05 * Tmp[i]);
	Out[105] = CountdownFrac;
	Out[106] = 0.f;
	for (int i = 0; i < NumTask; ++i) Out[107 + i] = Task.IsValidIndex(i) ? Task[i] : 0.f;
}

void FObsBuilder::ActionToCtrl(TConstArrayView<float> Action, TArray<float>& OutCtrl) const
{
	OutCtrl.SetNum(NumJoints);
	for (int32 i = 0; i < NumJoints; ++i)
	{
		const double A = Action.IsValidIndex(i) ? (double)Action[i] : 0.0;
		OutCtrl[i] = (float)FMath::Clamp(Nominal[i] + A * Half[i], Lo[i], Hi[i]);
	}
}
