#include "StreetballRewardConfig.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(StreetballRewardConfig)

UStreetballRewardConfig::UStreetballRewardConfig()
{
	// Same order and values as shared/reward_config.json "curriculum".
	AddStage(TEXT("l0_stand"), 0.95f, TEXT("eval success rate (Level.pass_fraction)"));
	AddStage(TEXT("l1_traverse"), 0.9f, TEXT("eval success rate (Level.pass_fraction)"));
	AddStage(TEXT("l2a_dribble_r"), 0.85f, TEXT("eval success rate (Level.pass_fraction)"));
	AddStage(TEXT("l2c_crossover"), 0.8f, TEXT("eval success rate (Level.pass_fraction)"));
	AddStage(TEXT("l3a_moving_dribble"), 0.75f, TEXT("eval success rate (Level.pass_fraction)"));
	AddStage(TEXT("l3b_scramble"), 0.8f, TEXT("eval success rate (Level.pass_fraction)"));
	AddStage(TEXT("l4_jump_shot"), 0.3f, TEXT("eval success rate (Level.pass_fraction)"));
}

void UStreetballRewardConfig::AddStage(const TCHAR* Stage, float Threshold, const TCHAR* Metric)
{
	FStreetballCurriculumStage& S = CurriculumStages.AddDefaulted_GetRef();
	S.Stage = Stage;
	S.Threshold = Threshold;
	S.Metric = Metric;
}

int32 UStreetballRewardConfig::FindStage(const FString& Stage) const
{
	return CurriculumStages.IndexOfByPredicate([&Stage](const FStreetballCurriculumStage& S) { return S.Stage == Stage; });
}
