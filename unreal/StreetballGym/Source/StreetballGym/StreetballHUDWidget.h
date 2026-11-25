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
	void UpdateTelemetry(const FString& ModeLabel, const FString& CameraLabel, const FString& PolicyLabel,
	                     int32 Seed, float EpisodeReward, int32 NanInfCount, float Fps, bool bPaused, bool bFallbackPolicy,
	                     float Exertion01 = 0.f, float PowerW = 0.f, float TimeScale = 1.f);
	void SetModeHint(const FString& HintText);
	void SetTelemetryVisible(bool bVisible);
	/** Grandma voice subtitle above the bottom bar; empty hides it. */
	void SetSubtitle(const FString& Text);
	FString GetSubtitle() const;
	bool IsTelemetryVisible() const { return bTelemetryVisible; }
	/** Trigger a GPU-cheap Slate screen wipe on camera cuts or demo mode transitions. */
	void TriggerScreenWipe(float DurationS = 0.18f);
	/** Trigger a brief accent highlight on HUD badges when user input fires an action. */
	void TriggerInputPulse();
	/** Version stamp yyMMdd (UTC date of the HEAD commit, from StreetballGym.Build.cs). */
	static FString BuildStampYYMMDD();
	/** Text shown bottom-right ("build YYMMDD"); empty until the widget tree exists. */
	FString GetBuildStampText() const;
	/** true when the narrow (portrait) layout is in use. */
	bool IsNarrowLayout() const { return LayoutMode == 1; }
	/** Below this width (Slate units) the HUD uses the stacked narrow layout. */
	static constexpr float NarrowWidth = 900.f;
	/** Wide (landscape): corner anchors. Narrow (portrait / phone width): the mode banner, policy badge, telemetry and
	 *  key hints stack bottom-left above the version stamp and wrap, so nothing overlaps at 9:16. */
	void ApplyLayout(const FVector2D& ViewSize);

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
	virtual void NativeTick(const FGeometry& MyGeometry, float InDeltaTime) override;
	virtual int32 NativePaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	                          FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;

	UPROPERTY() TObjectPtr<UVerticalBox> Root;
	UPROPERTY() TObjectPtr<UTextBlock> TierText;
	UPROPERTY() TObjectPtr<UTextBlock> StateText;
	UPROPERTY() TObjectPtr<UTextBlock> StreakText;
	UPROPERTY() TObjectPtr<UTextBlock> DistanceText;
	UPROPERTY() TObjectPtr<UTextBlock> MilestoneText;
	UPROPERTY() TObjectPtr<UTextBlock> CountdownText;
	UPROPERTY() TObjectPtr<UTextBlock> ProgressBarLabel;
	UPROPERTY() TObjectPtr<UProgressBar> ProgressBar;
	UPROPERTY() TObjectPtr<UTextBlock> StampText;
	UPROPERTY() TObjectPtr<UTextBlock> ModeBannerText;
	UPROPERTY() TObjectPtr<UTextBlock> PolicyFpsText;
	UPROPERTY() TObjectPtr<UTextBlock> TelemetryText;
	UPROPERTY() TObjectPtr<UTextBlock> BottomBarText;
	UPROPERTY() TObjectPtr<UTextBlock> SubtitleText;
	FString LastSubtitle;
	int32 LayoutMode = -1;   // -1 not laid out yet, 0 wide, 1 narrow
	float LayoutWidth = 0.f;

	bool bLoose = false;
	bool bTelemetryVisible = false;
	bool bTelemetryDirty = true;
	double LastTelemetryUpdateS = -1.0;
	FString LastModeLabel, LastCameraLabel, LastPolicyLabel, LastModeHint;
	bool bLastPaused = false;
	bool bLastFallbackPolicy = false;
	float LastTimeScale = 1.f;
	float CountdownFrac = 1.f;
	float ProgressPercent = 0.f;
	float DisplayedProgress01 = 0.f;
	float TargetProgress01 = 0.f;
	int32 LastTierNum = -1;
	float TierPopTimer = 0.f;
	float SubtitleFadeAlpha = 0.f;
	float WipeTimer = 0.f;
	float WipeDuration = 0.18f;
	float InputPulseTimer = 0.f;
	FString CachedTier, CachedStreak, CachedDistance, CachedMilestone;
};
