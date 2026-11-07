// Step 4 verification gate (contract section 6 / plan B6-B7), run inside Unreal against the
// same libmujoco the showcase uses:
//   Streetball.Gate.PresetActions : open-loop playback of the recorded ctrl sequence
//   Streetball.Gate.LivePhysics   : closed loop - obs builder -> NNE policy -> action rule -> 10 substeps
// Inputs (CVars, defaults relative to <repo>/shared):
//   streetball.GateReplay  = golden/replay_l0.json   (sim/tools/replay_recorder.py policy mode)
//   streetball.GatePolicy  = policies/l0_stand.onnx
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

static TAutoConsoleVariable<FString> CVarGateReplay(TEXT("streetball.GateReplay"), TEXT("golden/replay_l0.json"),
	TEXT("Policy-mode replay JSON for the Step 4 gate (relative to <repo>/shared or absolute)"), ECVF_Default);
static TAutoConsoleVariable<FString> CVarGatePolicy(TEXT("streetball.GatePolicy"), TEXT("policies/l0_stand.onnx"),
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
		return true;
	}

	struct FGateStats
	{
		double MaxRootCm = 0, MaxJointDeg = 0, MaxObs = 0, MaxAction = 0;
		int32 FootMismatchSteps = 0, Steps = 0;
		double RootCmAt1s = 0, RootCmAt5s = 0;
		double MinPelvisZ = 1e9;   // athlete must stay upright: parity alone passed while both sides fell (2026-11-07)
		FString Note;
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
	for (int32 t = 0; t < R.Steps; ++t)
	{
		B.Compute(Sim, Prev, Task, 0.f, 1.f, Obs);                      // task zeros, in_control 0, countdown 1
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
	}
	const bool bPass = G.MaxRootCm < 2.0 && G.MaxJointDeg < 1.0 && G.MinPelvisZ >= 0.7;
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
	WriteGateReport(TEXT("Live physics (closed loop)"), Body);
	AddInfo(FString::Printf(TEXT("closed loop %d steps: root %.4f cm, joints %.5f deg, obs %.3e, action %.3e, foot mismatches %d -> %s"),
		R.Steps, G.MaxRootCm, G.MaxJointDeg, G.MaxObs, G.MaxAction, G.FootMismatchSteps, bPass ? TEXT("PASS") : TEXT("FAIL")));
	TestTrue(TEXT("root < 2 cm"), G.MaxRootCm < 2.0);
	TestTrue(TEXT("joints < 1 deg"), G.MaxJointDeg < 1.0);
	TestTrue(TEXT("athlete upright (pelvis >= 0.7 m)"), G.MinPelvisZ >= 0.7);
	Policy->RemoveFromRoot(); Sim->Unload(); Sim->RemoveFromRoot();
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
