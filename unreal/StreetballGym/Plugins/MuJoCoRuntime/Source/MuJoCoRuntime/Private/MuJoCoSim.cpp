#include "MuJoCoSim.h"
#include "Misc/Paths.h"

void UMuJoCoSim::BeginDestroy()
{
	Unload();
	Super::BeginDestroy();
}

bool UMuJoCoSim::LoadXml(const FString& Path)
{
	Unload();
	char Error[1024] = {0};
	const FString Full = FPaths::ConvertRelativePathToFull(Path);
	Model = mj_loadXML(TCHAR_TO_UTF8(*Full), nullptr, Error, sizeof(Error));
	if (!Model)
	{
		UE_LOG(LogMuJoCo, Error, TEXT("mj_loadXML(%s) failed: %s"), *Full, UTF8_TO_TCHAR(Error));
		return false;
	}
	Data = mj_makeData(Model);
	mj_forward(Model, Data);
	UE_LOG(LogMuJoCo, Log, TEXT("Loaded %s: nq=%d nv=%d nu=%d nbody=%d ngeom=%d dt=%.4f"),
		*Full, Model->nq, Model->nv, Model->nu, Model->nbody, Model->ngeom, Model->opt.timestep);
	return true;
}

void UMuJoCoSim::Unload()
{
	if (Data) { mj_deleteData(Data); Data = nullptr; }
	if (Model) { mj_deleteModel(Model); Model = nullptr; }
}

void UMuJoCoSim::Step(int32 NumSteps)
{
	if (!IsLoaded()) return;
	for (int32 i = 0; i < NumSteps; ++i)
	{
		mj_step(Model, Data);
	}
}

void UMuJoCoSim::Forward()
{
	if (IsLoaded()) mj_forward(Model, Data);
}

bool UMuJoCoSim::ResetToKeyframe(const FString& KeyName)
{
	if (!IsLoaded()) return false;
	const int32 Key = KeyId(KeyName);
	if (Key < 0)
	{
		UE_LOG(LogMuJoCo, Error, TEXT("keyframe '%s' not found"), *KeyName);
		return false;
	}
	mj_resetDataKeyframe(Model, Data, Key);
	mj_forward(Model, Data);
	return true;
}

void UMuJoCoSim::ResetData()
{
	if (!IsLoaded()) return;
	mj_resetData(Model, Data);
	mj_forward(Model, Data);
}

// ---- ids --------------------------------------------------------------------
static int32 NameToId(const mjModel* M, mjtObj Type, const FString& Name)
{
	return M ? mj_name2id(M, Type, TCHAR_TO_UTF8(*Name)) : -1;
}
static FString IdToName(const mjModel* M, mjtObj Type, int32 Id)
{
	if (!M) return FString();
	const char* N = mj_id2name(M, Type, Id);
	return N ? UTF8_TO_TCHAR(N) : FString();
}

int32 UMuJoCoSim::BodyId(const FString& Name) const { return NameToId(Model, mjOBJ_BODY, Name); }
int32 UMuJoCoSim::JointId(const FString& Name) const { return NameToId(Model, mjOBJ_JOINT, Name); }
int32 UMuJoCoSim::ActuatorId(const FString& Name) const { return NameToId(Model, mjOBJ_ACTUATOR, Name); }
int32 UMuJoCoSim::SiteId(const FString& Name) const { return NameToId(Model, mjOBJ_SITE, Name); }
int32 UMuJoCoSim::GeomId(const FString& Name) const { return NameToId(Model, mjOBJ_GEOM, Name); }
int32 UMuJoCoSim::SensorId(const FString& Name) const { return NameToId(Model, mjOBJ_SENSOR, Name); }
int32 UMuJoCoSim::KeyId(const FString& Name) const { return NameToId(Model, mjOBJ_KEY, Name); }
FString UMuJoCoSim::BodyName(int32 Id) const { return IdToName(Model, mjOBJ_BODY, Id); }
FString UMuJoCoSim::GeomName(int32 Id) const { return IdToName(Model, mjOBJ_GEOM, Id); }
FString UMuJoCoSim::JointName(int32 Id) const { return IdToName(Model, mjOBJ_JOINT, Id); }

// ---- reads ------------------------------------------------------------------
FTransform UMuJoCoSim::GetBodyTransformUE(int32 Body) const
{
	if (!IsLoaded() || Body < 0 || Body >= Model->nbody) return FTransform::Identity;
	return FTransform(SimToUEQuat(Data->xquat + 4 * Body), SimToUEPos(Data->xpos + 3 * Body));
}

FVector UMuJoCoSim::GetSitePositionUE(int32 Site) const
{
	if (!IsLoaded() || Site < 0 || Site >= Model->nsite) return FVector::ZeroVector;
	return SimToUEPos(Data->site_xpos + 3 * Site);
}

FTransform UMuJoCoSim::GetGeomTransformUE(int32 Geom) const
{
	if (!IsLoaded() || Geom < 0 || Geom >= Model->ngeom) return FTransform::Identity;
	// geom_xmat is a world rotation matrix (row-major 3x3); convert to quaternion then to UE.
	double Q[4];
	mju_mat2Quat(Q, Data->geom_xmat + 9 * Geom);
	return FTransform(SimToUEQuat(Q), SimToUEPos(Data->geom_xpos + 3 * Geom));
}

int32 UMuJoCoSim::GetGeomType(int32 Geom) const
{
	return (IsLoaded() && Geom >= 0 && Geom < Model->ngeom) ? Model->geom_type[Geom] : -1;
}

FVector UMuJoCoSim::GetGeomSize(int32 Geom) const
{
	if (!IsLoaded() || Geom < 0 || Geom >= Model->ngeom) return FVector::ZeroVector;
	const double* S = Model->geom_size + 3 * Geom;
	return FVector(S[0], S[1], S[2]);
}

int32 UMuJoCoSim::GetGeomBody(int32 Geom) const
{
	return (IsLoaded() && Geom >= 0 && Geom < Model->ngeom) ? Model->geom_bodyid[Geom] : -1;
}

FLinearColor UMuJoCoSim::GetGeomColor(int32 Geom) const
{
	if (!IsLoaded() || Geom < 0 || Geom >= Model->ngeom) return FLinearColor::White;
	const float* C = Model->geom_rgba + 4 * Geom;
	return FLinearColor(C[0], C[1], C[2], C[3]);
}

bool UMuJoCoSim::IsBodyDynamic(int32 Body) const
{
	if (!IsLoaded() || Body < 0 || Body >= Model->nbody) return false;
	// A body is dynamic if it or any ancestor has dofs.
	int32 B = Body;
	while (B > 0)
	{
		if (Model->body_dofnum[B] > 0) return true;
		B = Model->body_parentid[B];
	}
	return false;
}

void UMuJoCoSim::GetBodyPosQuatSim(int32 Body, FVector3d& OutPos, FQuat4d& OutQuatWxyz) const
{
	if (!IsLoaded() || Body < 0 || Body >= Model->nbody) { OutPos = FVector3d::ZeroVector; OutQuatWxyz = FQuat4d::Identity; return; }
	const double* P = Data->xpos + 3 * Body;
	const double* Q = Data->xquat + 4 * Body;
	OutPos = FVector3d(P[0], P[1], P[2]);
	OutQuatWxyz = FQuat4d(Q[1], Q[2], Q[3], Q[0]);   // stored as X,Y,Z,W but values are the raw MuJoCo components
}

FVector3d UMuJoCoSim::GetSubtreeAngMomSim(int32 Body)
{
	if (!IsLoaded() || Body < 0 || Body >= Model->nbody) return FVector3d::ZeroVector;
	mj_subtreeVel(Model, Data);
	const double* L = Data->subtree_angmom + 3 * Body;
	return FVector3d(L[0], L[1], L[2]);
}

FVector3d UMuJoCoSim::GetBodyLinearVelocitySim(int32 Body) const
{
	if (!IsLoaded() || Body < 0 || Body >= Model->nbody) return FVector3d::ZeroVector;
	// cvel is the 6D velocity [rot; lin] of the body, expressed at the subtree COM of its kinematic
	// root. Velocity of the body origin: v = lin + rot x (xpos - subtree_com[root]).
	const int32 Root = Model->body_rootid[Body];
	const double* CV = Data->cvel + 6 * Body;
	const double* P = Data->xpos + 3 * Body;
	const double* C = Data->subtree_com + 3 * Root;
	const FVector3d Rot(CV[0], CV[1], CV[2]), Lin(CV[3], CV[4], CV[5]);
	const FVector3d R(P[0] - C[0], P[1] - C[1], P[2] - C[2]);
	return Lin + FVector3d::CrossProduct(Rot, R);
}

TConstArrayView<double> UMuJoCoSim::QPos() const { return IsLoaded() ? TConstArrayView<double>(Data->qpos, Model->nq) : TConstArrayView<double>(); }
TConstArrayView<double> UMuJoCoSim::QVel() const { return IsLoaded() ? TConstArrayView<double>(Data->qvel, Model->nv) : TConstArrayView<double>(); }
TConstArrayView<double> UMuJoCoSim::SensorData() const { return IsLoaded() ? TConstArrayView<double>(Data->sensordata, Model->nsensordata) : TConstArrayView<double>(); }

double UMuJoCoSim::GetSensorValue(int32 Sensor, int32 Component) const
{
	if (!IsLoaded() || Sensor < 0 || Sensor >= Model->nsensor) return 0.0;
	return Data->sensordata[Model->sensor_adr[Sensor] + Component];
}

// ---- writes -----------------------------------------------------------------
void UMuJoCoSim::SetCtrl(TConstArrayView<float> Ctrl)
{
	if (!IsLoaded()) return;
	const int32 N = FMath::Min(Ctrl.Num(), Model->nu);
	for (int32 i = 0; i < N; ++i) Data->ctrl[i] = Ctrl[i];
}

void UMuJoCoSim::SetCtrlDouble(TConstArrayView<double> Ctrl)
{
	if (!IsLoaded()) return;
	const int32 N = FMath::Min(Ctrl.Num(), Model->nu);
	for (int32 i = 0; i < N; ++i) Data->ctrl[i] = Ctrl[i];
}

void UMuJoCoSim::SetQPos(TConstArrayView<double> InQPos)
{
	if (!IsLoaded()) return;
	const int32 N = FMath::Min(InQPos.Num(), Model->nq);
	for (int32 i = 0; i < N; ++i) Data->qpos[i] = InQPos[i];
}

void UMuJoCoSim::SetQVel(TConstArrayView<double> InQVel)
{
	if (!IsLoaded()) return;
	const int32 N = FMath::Min(InQVel.Num(), Model->nv);
	for (int32 i = 0; i < N; ++i) Data->qvel[i] = InQVel[i];
}

// ---- contacts ---------------------------------------------------------------
void UMuJoCoSim::GetContacts(TArray<FMjContact>& Out) const
{
	Out.Reset();
	if (!IsLoaded()) return;
	Out.Reserve(Data->ncon);
	double F[6];
	for (int32 i = 0; i < Data->ncon; ++i)
	{
		const mjContact& C = Data->contact[i];
		FMjContact& O = Out.AddDefaulted_GetRef();
		O.Geom1 = C.geom[0];
		O.Geom2 = C.geom[1];
		O.Geom1Name = GeomName(O.Geom1);
		O.Geom2Name = GeomName(O.Geom2);
		O.PositionUE = SimToUEPos(C.pos);
		O.Distance = (float)C.dist;
		mj_contactForce(Model, Data, i, F);
		O.NormalForce = (float)F[0];
	}
}

uint64 UMuJoCoSim::HashQPos() const
{
	if (!IsLoaded()) return 0;
	// FNV-1a over the raw bytes; order-sensitive and exact.
	uint64 H = 1469598103934665603ull;
	const uint8* B = reinterpret_cast<const uint8*>(Data->qpos);
	const int32 N = Model->nq * sizeof(double);
	for (int32 i = 0; i < N; ++i) { H ^= B[i]; H *= 1099511628211ull; }
	return H;
}
