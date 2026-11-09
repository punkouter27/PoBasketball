// Step 4 verification gate (contract section 6 / plan B6-B7), run inside Unreal against the
// same libmujoco the showcase uses:
//   Streetball.Gate.PresetActions : open-loop playback of the recorded ctrl sequence
//   Streetball.Gate.LivePhysics   : closed loop - obs builder -> NNE policy -> action rule -> 10 substeps
// Inputs (CVars, defaults relative to <repo>/shared):
//   streetball.GateReplay  = golden/replay_balance.json   (sim/tools/replay_recorder.py policy --level l0_stand)
//   streetball.GatePolicy  = policies/balance.onnx (production balance; replay_l0.json/l0_stand.onnx were a stale pair)
// Both tests pass-with-SKIPPED when the files are absent and write docs/phase_reports/Step4_gate_unreal.md.
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "StreetballGym.h"
#include "MuJoCoSim.h"
#include "ObsBuilder.h"
#include "PolicyRunner.h"
#include "HAL/IConsoleManager.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

static TAutoConsoleVariable<FString> CVarGateReplay(TEXT("streetball.GateReplay"), TEXT("golden/replay_balance.json"),
	TEXT("Policy-mode replay JSON for the Step 4 gate (relative to <repo>/shared or absolute)"), ECVF_Default);
static TAutoConsoleVariable<FString> CVarGatePolicy(TEXT("streetball.GatePolicy"), TEXT("policies/balance.onnx"),
	TEXT("ONNX policy for the Step 4 live-physics gate (relative to <repo>/shared or absolute)"), ECVF_Default);

namespace
{
	constexpr EAutomationTestFlags GFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

	FString ResolveShared(const FString& P)
	{
		return FPaths::IsRelative(P) ? FPaths::Combine(Streetball::RepoSharedDir(), P) : P;
	}

	struct FReplay
	{
		int32 Steps = 0, Substeps = 10, NQ = 0, NU = 0, NObs = 0;
		FString Mode, Key;
		TArray<double> QPos0, QVel0;
		TArray<TArray<double>> Ctrl, QPos, Obs, Action;
		// optional (recorder 2026-11-08): per-step task block / ball-control inputs and kinematics for the 5 s rollout gate
		FString Level;
		TArray<TArray<double>> Task, QVel, AngMom;
		TArray<double> InControl, Countdown;
	};

	bool LoadReplay(const FString& Path, FReplay& R, FString& Err)
	{
		FString S;
		if (!FFileHelper::LoadFileToString(S, *Path)) { Err = TEXT("cannot read ") + Path; return false; }
		TSharedPtr<FJsonObject> J;
		if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(S), J) || !J.IsValid()) { Err = TEXT("bad JSON ") + Path; return false; }
		auto Vec = [](const TArray<TSharedPtr<FJsonValue>>& A, TArray<double>& Out) { Out.Reset(A.Num()); for (const auto& V : A) Out.Add(V->AsNumber()); };
		auto Mat = [&](const TCHAR* Field, TArray<TArray<double>>& Out) {
			const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
			if (!J->TryGetArrayField(Field, Rows)) return;
			Out.SetNum(Rows->Num());
			for (int32 i = 0; i < Rows->Num(); ++i) Vec((*Rows)[i]->AsArray(), Out[i]);
		};
		R.Mode = J->GetStringField(TEXT("mode"));
		R.Key = J->GetStringField(TEXT("key"));
		R.Steps = (int32)J->GetNumberField(TEXT("steps"));
		R.Substeps = (int32)J->GetNumberField(TEXT("substeps"));
		R.NQ = (int32)J->GetNumberField(TEXT("nq"));
		R.NU = (int32)J->GetNumberField(TEXT("nu"));
		R.NObs = J->HasField(TEXT("n_obs")) ? (int32)J->GetNumberField(TEXT("n_obs")) : 0;
		Vec(J->GetArrayField(TEXT("qpos0")), R.QPos0);
		Vec(J->GetArrayField(TEXT("qvel0")), R.QVel0);
		Mat(TEXT("ctrl"), R.Ctrl); Mat(TEXT("qpos"), R.QPos); Mat(TEXT("obs"), R.Obs); Mat(TEXT("action"), R.Action);
		Mat(TEXT("task"), R.Task); Mat(TEXT("qvel"), R.QVel); Mat(TEXT("angmom"), R.AngMom);
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (J->TryGetArrayField(TEXT("in_control"), Arr)) Vec(*Arr, R.InControl);
		if (J->TryGetArrayField(TEXT("countdown"), Arr)) Vec(*Arr, R.Countdown);
		J->TryGetStringField(TEXT("level"), R.Level);
		return true;
	}

	struct FGateStats
	{
		double MaxRootCm = 0, MaxJointDeg = 0, MaxObs = 0, MaxAction = 0;
		int32 FootMismatchSteps = 0, Steps = 0;
		double RootCmAt1s = 0, RootCmAt5s = 0;
		double MinPelvisZ = 1e9;   // athlete must stay upright: parity alone passed while both sides fell (2026-11-07)
		FString Note;
		// 5 s rollout gate (UU_AGENT §4, 2026-11-08), report-only until thresholds are set from measured baselines
		double MaxRootVelErr = -1, MaxAngMomErr = -1, MaxAngMom = 0;   // -1 = replay has no reference
		double MaxFootSlide = 0, MeanFootSlide = 0, MaxPenetrationMm = 0;
		int32 SlideSamples = 0, FootFlips[2] = {0, 0};
	};

	/** Contacts and kinematics the 5 s rollout gate measures on the Unreal side after each control step. */
	struct FRolloutProbe
	{
		int32 Floor = -1, FootGeom[2] = {-1, -1}, FootBody[2] = {-1, -1}, Pelvis = -1, RootV = 0;
		bool PrevContact[2] = {false, false}, bHavePrev = false;
		FVector2d PrevFoot[2];

		void Init(const UMuJoCoSim* Sim)
		{
			Floor = Sim->GeomId(TEXT("floor"));
			FootGeom[0] = Sim->GeomId(TEXT("foot_l")); FootGeom[1] = Sim->GeomId(TEXT("foot_r"));
			FootBody[0] = Sim->BodyId(TEXT("foot_l")); FootBody[1] = Sim->BodyId(TEXT("foot_r"));
			Pelvis = Sim->BodyId(TEXT("pelvis"));
			RootV = Sim->GetModel()->jnt_dofadr[Sim->JointId(TEXT("root"))];
		}

		void Step(UMuJoCoSim* Sim, const FReplay& R, int32 t, double ControlDt, FGateStats& G)
		{
			const mjData* D = Sim->GetData();
			bool Contact[2] = {false, false};
			for (int32 c = 0; c < D->ncon; ++c)
			{
				const int32 g0 = D->contact[c].geom[0], g1 = D->contact[c].geom[1];
				if (g0 != Floor && g1 != Floor) continue;
				const int32 Other = g0 == Floor ? g1 : g0;
				G.MaxPenetrationMm = FMath::Max(G.MaxPenetrationMm, -FMath::Min(0.0, (double)D->contact[c].dist) * 1000.0);
				if (Other == FootGeom[0]) Contact[0] = true;
				if (Other == FootGeom[1]) Contact[1] = true;
			}
			for (int32 i = 0; i < 2; ++i)
			{
				const FVector2d P(D->xpos[3 * FootBody[i]], D->xpos[3 * FootBody[i] + 1]);
				if (bHavePrev)
				{
					if (Contact[i] != PrevContact[i]) ++G.FootFlips[i];
					if (Contact[i] && PrevContact[i])   // planted on both samples: any horizontal motion is sliding
					{
						const double V = (P - PrevFoot[i]).Length() / ControlDt;
						G.MaxFootSlide = FMath::Max(G.MaxFootSlide, V);
						G.MeanFootSlide += V; ++G.SlideSamples;
					}
				}
				PrevFoot[i] = P; PrevContact[i] = Contact[i];
			}
			bHavePrev = true;
			if (R.QVel.IsValidIndex(t))
			{
				const double E = FVector3d(D->qvel[RootV] - R.QVel[t][RootV], D->qvel[RootV + 1] - R.QVel[t][RootV + 1], D->qvel[RootV + 2] - R.QVel[t][RootV + 2]).Length();
				G.MaxRootVelErr = FMath::Max(G.MaxRootVelErr, E);
			}
			const FVector3d L = Sim->GetSubtreeAngMomSim(Pelvis);
			G.MaxAngMom = FMath::Max(G.MaxAngMom, L.Length());
			if (R.AngMom.IsValidIndex(t))
				G.MaxAngMomErr = FMath::Max(G.MaxAngMomErr, (L - FVector3d(R.AngMom[t][0], R.AngMom[t][1], R.AngMom[t][2])).Length());
		}
	};

	void CompareQ(const UMuJoCoSim* Sim, const TArray<double>& Rec, int32 RootQ, const TArray<int32>& JAdr, FGateStats& G, int32 t, int32 Steps)
	{
		const TConstArrayView<double> Q = Sim->QPos();
		const double R = FMath::Sqrt(FMath::Square(Q[RootQ] - Rec[RootQ]) + FMath::Square(Q[RootQ + 1] - Rec[RootQ + 1]) + FMath::Square(Q[RootQ + 2] - Rec[RootQ + 2])) * 100.0;
		G.MaxRootCm = FMath::Max(G.MaxRootCm, R);
		for (int32 a : JAdr) G.MaxJointDeg = FMath::Max(G.MaxJointDeg, FMath::RadiansToDegrees(FMath::Abs(Q[a] - Rec[a])));
		if (t == FMath::Min(49, Steps - 1)) G.RootCmAt1s = R;
		if (t == Steps - 1) G.RootCmAt5s = R;
	}

	void WriteGateReport(const FString& Section, const FString& Body)
	{
		const FString Path = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("../../docs/phase_reports/Step4_gate_unreal.md")));
		FString Existing;
		FFileHelper::LoadFileToString(Existing, *Path);
		// Replace or append the section (sections are delimited by "## " headings).
		const FString Header = TEXT("## ") + Section;
		int32 Start = Existing.Find(Header);
		FString Out;
		if (Start == INDEX_NONE)
		{
			if (Existing.IsEmpty()) Existing = TEXT("# Step 4 verification gate - Unreal side\n\nWritten by the Streetball.Gate.* automation tests (libmujoco 4.0.0 in UE 5.8.4).\n\n");
			Out = Existing + Header + TEXT("\n\n") + Body + TEXT("\n\n");
		}
		else
		{
			int32 End = Existing.Find(TEXT("\n## "), ESearchCase::CaseSensitive, ESearchDir::FromStart, Start + Header.Len());
			if (End == INDEX_NONE) End = Existing.Len();
			Out = Existing.Left(Start) + Header + TEXT("\n\n") + Body + TEXT("\n\n") + Existing.Mid(End + 1);
		}
		FFileHelper::SaveStringToFile(Out, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}

	bool GateSetup(FAutomationTestBase& T, const TCHAR* Section, bool bNeedPolicy, FReplay& R, FString& ReplayPath, FString& PolicyPath, bool& bSkipped)
	{
		bSkipped = false;
		// Command-line switches win (-GateReplay=<path> -GatePolicy=<path>); a string CVar set through
		// -ExecCmds swallows the rest of the ExecCmds line, so never pass the paths that way.
		FString ReplayArg, PolicyArg;
		if (!FParse::Value(FCommandLine::Get(), TEXT("-GateReplay="), ReplayArg)) ReplayArg = CVarGateReplay.GetValueOnGameThread();
		if (!FParse::Value(FCommandLine::Get(), TEXT("-GatePolicy="), PolicyArg)) PolicyArg = CVarGatePolicy.GetValueOnGameThread();
		ReplayPath = ResolveShared(ReplayArg.TrimQuotes());
		PolicyPath = ResolveShared(PolicyArg.TrimQuotes());
		FString Missing;
		if (!FPaths::FileExists(ReplayPath)) Missing += TEXT(" replay: ") + ReplayPath;
		if (bNeedPolicy && !FPaths::FileExists(PolicyPath)) Missing += TEXT(" policy: ") + PolicyPath;
		if (!Missing.IsEmpty())
		{
			const FString Msg = FString::Printf(TEXT("SKIPPED - input file(s) absent:%s. Set CVars streetball.GateReplay / streetball.GatePolicy or produce them with sim/tools/replay_recorder.py policy and export_onnx.py."), *Missing);
			T.AddInfo(Msg);
			WriteGateReport(Section, Msg);
			bSkipped = true;
			return false;
		}
		FString Err;
		if (!LoadReplay(ReplayPath, R, Err)) { T.AddError(Err); return false; }
		return true;
	}

	void CollectAdr(const UMuJoCoSim* Sim, int32& RootQ, TArray<int32>& JAdr)
	{
		const mjModel* M = Sim->GetModel();
		RootQ = M->jnt_qposadr[Sim->JointId(TEXT("root"))];
		JAdr.Reset();
		for (int32 i = 0; i < M->nu; ++i) JAdr.Add(M->jnt_qposadr[M->actuator_trnid[2 * i]]);
	}
}

// ---------------------------------------------------------------------------- open loop
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballGatePresetTest, "Streetball.Gate.PresetActions", GFlags)
bool FStreetballGatePresetTest::RunTest(const FString&)
{
	FReplay R; FString ReplayPath, PolicyPath; bool bSkipped;
	if (!GateSetup(*this, TEXT("Preset actions (open loop)"), false, R, ReplayPath, PolicyPath, bSkipped)) return bSkipped;

	UMuJoCoSim* Sim = NewObject<UMuJoCoSim>(GetTransientPackage()); Sim->AddToRoot();
	if (!TestTrue(TEXT("scene loads"), Sim->LoadXml(Streetball::SceneXmlPath()))) { Sim->RemoveFromRoot(); return false; }
	TestEqual(TEXT("nq"), R.NQ, Sim->NumQ());
	Sim->ResetToKeyframe(R.Key);
	Sim->SetQPos(R.QPos0); Sim->SetQVel(R.QVel0); Sim->Forward();
	int32 RootQ; TArray<int32> JAdr; CollectAdr(Sim, RootQ, JAdr);

	FGateStats G; G.Steps = R.Steps;
	for (int32 t = 0; t < R.Steps; ++t)
	{
		Sim->SetCtrlDouble(R.Ctrl[t]);
		Sim->Step(R.Substeps);
		CompareQ(Sim, R.QPos[t], RootQ, JAdr, G, t, R.Steps);
	}
	const bool bPass = G.MaxRootCm < 2.0 && G.MaxJointDeg < 1.0;
	const FString Body = FString::Printf(
		TEXT("Replay: `%s` (mode %s, %d steps x %d substeps = %.1f s)\n\n| Metric | Value | Gate |\n|---|---|---|\n| Max root position error | %.4f cm | < 2 cm |\n| Max joint error | %.5f deg | < 1 deg |\n| Root error at 1 s / end | %.4f / %.4f cm | - |\n\n**%s**"),
		*ReplayPath, *R.Mode, R.Steps, R.Substeps, R.Steps * R.Substeps * 0.002, G.MaxRootCm, G.MaxJointDeg, G.RootCmAt1s, G.RootCmAt5s, bPass ? TEXT("PASS") : TEXT("FAIL"));
	WriteGateReport(TEXT("Preset actions (open loop)"), Body);
	AddInfo(FString::Printf(TEXT("open loop %d steps: max root %.4f cm, max joint %.5f deg -> %s"), R.Steps, G.MaxRootCm, G.MaxJointDeg, bPass ? TEXT("PASS") : TEXT("FAIL")));
	TestTrue(TEXT("root < 2 cm"), G.MaxRootCm < 2.0);
	TestTrue(TEXT("joints < 1 deg"), G.MaxJointDeg < 1.0);
	Sim->Unload(); Sim->RemoveFromRoot();
	return true;
}

// ---------------------------------------------------------------------------- closed loop
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballGateLiveTest, "Streetball.Gate.LivePhysics", GFlags)
bool FStreetballGateLiveTest::RunTest(const FString&)
{
	FReplay R; FString ReplayPath, PolicyPath; bool bSkipped;
	if (!GateSetup(*this, TEXT("Live physics (closed loop)"), true, R, ReplayPath, PolicyPath, bSkipped)) return bSkipped;
	if (R.Obs.Num() != R.Steps || R.Action.Num() != R.Steps)
	{
		const FString Msg = FString::Printf(TEXT("SKIPPED - %s is not a policy-mode replay (no obs/action arrays)"), *ReplayPath);
		AddInfo(Msg); WriteGateReport(TEXT("Live physics (closed loop)"), Msg);
		return true;
	}

	UMuJoCoSim* Sim = NewObject<UMuJoCoSim>(GetTransientPackage()); Sim->AddToRoot();
	if (!TestTrue(TEXT("scene loads"), Sim->LoadXml(Streetball::SceneXmlPath()))) { Sim->RemoveFromRoot(); return false; }
	UPolicyRunner* Policy = NewObject<UPolicyRunner>(GetTransientPackage()); Policy->AddToRoot();
	if (!TestTrue(TEXT("policy loads"), Policy->LoadOnnx(PolicyPath, FObsBuilder::NumObs, FObsBuilder::NumAction))) { Policy->RemoveFromRoot(); Sim->RemoveFromRoot(); return false; }
	FObsBuilder B;
	if (!TestTrue(TEXT("obs builder"), B.Initialize(Sim, Streetball::ObsSpecPath()))) { Policy->RemoveFromRoot(); Sim->RemoveFromRoot(); return false; }

	// Exactly the recorder: keyframe, qpos0/qvel0, one forward, then obs -> policy -> clip -> ctrl -> substeps
	Sim->ResetToKeyframe(R.Key);
	Sim->SetQPos(R.QPos0); Sim->SetQVel(R.QVel0); Sim->Forward();
	int32 RootQ; TArray<int32> JAdr; CollectAdr(Sim, RootQ, JAdr);

	TArray<float> Prev; Prev.SetNumZeroed(FObsBuilder::NumJoints);
	TArray<float> Task; Task.SetNumZeroed(FObsBuilder::NumTask);
	TArray<float> Obs, Act, Ctrl;
	FGateStats G; G.Steps = R.Steps;
	int32 WorstObsSlot = -1, WorstObsStep = -1;
	double InferenceMs = 0.0;
	FRolloutProbe Probe; Probe.Init(Sim);
	const double ControlDt = R.Substeps * Sim->GetTimestep();
	const double DurationS = R.Steps * ControlDt;
	for (int32 t = 0; t < R.Steps; ++t)
	{
		// per-step task block and ball-control inputs from the recording (older replays: zeros / 0 / 1)
		if (R.Task.IsValidIndex(t)) for (int32 k = 0; k < FObsBuilder::NumTask && k < R.Task[t].Num(); ++k) Task[k] = (float)R.Task[t][k];
		const float InCtrl = R.InControl.IsValidIndex(t) ? (float)R.InControl[t] : 0.f;
		const float Countdown = R.Countdown.IsValidIndex(t) ? (float)R.Countdown[t] : 1.f;
		B.Compute(Sim, Prev, Task, InCtrl, Countdown, Obs);
		for (int32 k = 0; k < FObsBuilder::NumObs; ++k)
		{
			const double D = FMath::Abs((double)Obs[k] - R.Obs[t][k]);
			if (D > G.MaxObs) { G.MaxObs = D; WorstObsSlot = k; WorstObsStep = t; }
		}
		if ((Obs[99] > 0.5f) != (R.Obs[t][99] > 0.5) || (Obs[100] > 0.5f) != (R.Obs[t][100] > 0.5)) ++G.FootMismatchSteps;
		if (!Policy->Run(Obs, Act)) { AddError(TEXT("policy run failed")); break; }
		InferenceMs += Policy->LastInferenceMs;
		for (float& A : Act) A = FMath::Clamp(A, -1.f, 1.f);
		for (int32 k = 0; k < FObsBuilder::NumAction; ++k) G.MaxAction = FMath::Max(G.MaxAction, FMath::Abs((double)Act[k] - R.Action[t][k]));
		B.ActionToCtrl(Act, Ctrl);
		Sim->SetCtrl(Ctrl);
		Sim->Step(R.Substeps);
		Prev = Act;
		CompareQ(Sim, R.QPos[t], RootQ, JAdr, G, t, R.Steps);
		G.MinPelvisZ = FMath::Min(G.MinPelvisZ, Sim->QPos()[RootQ + 2]);
		Probe.Step(Sim, R, t, ControlDt, G);
	}
	if (G.SlideSamples > 0) G.MeanFootSlide /= G.SlideSamples;
	const bool bLongEnough = DurationS >= 4.999;
	const bool bPass = G.MaxRootCm < 2.0 && G.MaxJointDeg < 1.0 && G.MinPelvisZ >= 0.7 && bLongEnough;
	const FString Rollout = FString::Printf(
		TEXT("\n\n### 5 s rollout gate (UU_AGENT section 4) - report only, thresholds to be set from these baselines\n\n")
		TEXT("Level `%s`, %.2f s.\n\n| Metric | Value |\n|---|---|\n")
		TEXT("| Max root linear velocity error vs recorded | %s |\n")
		TEXT("| Max whole-body angular momentum error vs recorded | %s |\n")
		TEXT("| Max whole-body angular momentum (Unreal) | %.3f kg m^2/s |\n")
		TEXT("| Foot sliding while planted: max / mean | %.3f / %.3f m/s (%d samples) |\n")
		TEXT("| Max ground penetration (any geom vs floor) | %.2f mm |\n")
		TEXT("| Foot contact flips (chatter): left / right | %d / %d (%.1f / %.1f per s) |"),
		R.Level.IsEmpty() ? TEXT("l0_stand (legacy replay)") : *R.Level, DurationS,
		G.MaxRootVelErr < 0 ? TEXT("n/a (replay has no qvel)") : *FString::Printf(TEXT("%.2e m/s"), G.MaxRootVelErr),
		G.MaxAngMomErr < 0 ? TEXT("n/a (replay has no angmom)") : *FString::Printf(TEXT("%.2e kg m^2/s"), G.MaxAngMomErr),
		G.MaxAngMom, G.MaxFootSlide, G.MeanFootSlide, G.SlideSamples, G.MaxPenetrationMm,
		G.FootFlips[0], G.FootFlips[1], G.FootFlips[0] / FMath::Max(DurationS, 1e-6), G.FootFlips[1] / FMath::Max(DurationS, 1e-6));
	const FString Body = FString::Printf(
		TEXT("Replay: `%s`, policy: `%s` (%d steps x %d substeps = %.1f s, closed loop in Unreal with NNE ORT-CPU)\n\n")
		TEXT("| Metric | Value | Gate |\n|---|---|---|\n")
		TEXT("| Max root position error vs recorded | %.4f cm | < 2 cm |\n")
		TEXT("| Max joint error vs recorded | %.5f deg | < 1 deg |\n")
		TEXT("| Root error at 1 s / end | %.4f / %.4f cm | - |\n")
		TEXT("| Max abs obs diff (C++ builder vs Python) | %.3e (slot %d, step %d) | report |\n")
		TEXT("| Max abs action diff (NNE vs onnxruntime) | %.3e | report |\n")
		TEXT("| Foot-contact flag mismatched steps | %d / %d | report |\n")
		TEXT("| Mean inference | %.3f ms | < 2 ms |\n")
		TEXT("| Lowest pelvis height (athlete upright) | %.3f m | >= 0.70 m |\n\n**%s**"),
		*ReplayPath, *PolicyPath, R.Steps, R.Substeps, R.Steps * R.Substeps * 0.002,
		G.MaxRootCm, G.MaxJointDeg, G.RootCmAt1s, G.RootCmAt5s, G.MaxObs, WorstObsSlot, WorstObsStep, G.MaxAction,
		G.FootMismatchSteps, R.Steps, InferenceMs / FMath::Max(1, R.Steps), G.MinPelvisZ, bPass ? TEXT("PASS") : TEXT("FAIL"));
	WriteGateReport(TEXT("Live physics (closed loop)"), Body + Rollout);
	AddInfo(Rollout);
	TestTrue(TEXT("rollout lasts >= 5 s"), bLongEnough);
	AddInfo(FString::Printf(TEXT("closed loop %d steps: root %.4f cm, joints %.5f deg, obs %.3e, action %.3e, foot mismatches %d -> %s"),
		R.Steps, G.MaxRootCm, G.MaxJointDeg, G.MaxObs, G.MaxAction, G.FootMismatchSteps, bPass ? TEXT("PASS") : TEXT("FAIL")));
	TestTrue(TEXT("root < 2 cm"), G.MaxRootCm < 2.0);
	TestTrue(TEXT("joints < 1 deg"), G.MaxJointDeg < 1.0);
	TestTrue(TEXT("athlete upright (pelvis >= 0.7 m)"), G.MinPelvisZ >= 0.7);
	Policy->RemoveFromRoot(); Sim->Unload(); Sim->RemoveFromRoot();
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
