#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "StreetballDirector.h"
#include "StreetballHUDWidget.generated.h"

class UTextBlock;
class UProgressBar;
class UVerticalBox;

/**
 * PRD section 6 scoreboard, built entirely in C++ (no UMG asset): active tier, clean-dribble
 * streak, cumulative distance, milestone bar with checkmarks + % progress, and a countdown
 * ring (drawn in NativePaint) that is visible only while the ball is loose.
 */
UCLASS()
class STREETBALLGYM_API UStreetballHUDWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	void UpdateFromProgress(const FStreetballProgress& P, EStreetballState State);
	/** Compile date as YYMMDD for the UU_AGENT build stamp. */
	static FString BuildStampYYMMDD();
	/** Text shown bottom-right ("build YYMMDD"); empty until the widget tree exists. */
	FString GetBuildStampText() const;

	// exposed for tests
	FString GetTierText() const;
	FString GetStreakText() const;
	FString GetDistanceText() const;
	FString GetMilestoneText() const;
	float GetProgressPercent() const;
	bool IsCountdownVisible() const { return bLoose; }
	float GetCountdownFrac() const { return CountdownFrac; }

protected:
	virtual TSharedRef<SWidget> RebuildWidget() override;
	virtual int32 NativePaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	                          FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;

	UPROPERTY() TObjectPtr<UVerticalBox> Root;
	UPROPERTY() TObjectPtr<UTextBlock> TierText;
	UPROPERTY() TObjectPtr<UTextBlock> StateText;
	UPROPERTY() TObjectPtr<UTextBlock> StreakText;
	UPROPERTY() TObjectPtr<UTextBlock> DistanceText;
	UPROPERTY() TObjectPtr<UTextBlock> MilestoneText;
	UPROPERTY() TObjectPtr<UTextBlock> CountdownText;
	UPROPERTY() TObjectPtr<UProgressBar> ProgressBar;
	UPROPERTY() TObjectPtr<UTextBlock> StampText;

	bool bLoose = false;
	float CountdownFrac = 1.f;
	float ProgressPercent = 0.f;
	FString CachedTier, CachedStreak, CachedDistance, CachedMilestone;
};
