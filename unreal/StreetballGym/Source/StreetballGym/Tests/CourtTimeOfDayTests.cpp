#include "Misc/AutomationTest.h"
#include "CourtTimeOfDay.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCourtTimeOfDayModelTest, "Streetball.Showcase.TimeOfDayModel",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FCourtTimeOfDayModelTest::RunTest(const FString&)
{
	const float Max = 60.f, RefYaw = 35.f, On = 18.5f, Off = 6.f;
	// the level's sun (pitch -55) maps back to itself: same pitch and yaw at the reference hour
	const float Ref = FCourtSkyState::AfternoonHourForElevation(55.f, Max);
	TestTrue(TEXT("reference hour is afternoon"), Ref > 12.f && Ref < 18.f);
	const FCourtSkyState A = FCourtSkyState::Evaluate(Ref, Max, Ref, RefYaw, On, Off);
	TestEqual(TEXT("start pitch = level sun"), A.LightPitchDeg, -55.f, 0.01f);
	TestEqual(TEXT("start yaw = level sun"), A.LightYawDeg, RefYaw, 0.01f);
	TestEqual(TEXT("full sun at start"), A.LightScale, 1.f, 1e-4f);
	TestFalse(TEXT("lamps off by day"), A.LampScale > 0.f);

	const FCourtSkyState Noon = FCourtSkyState::Evaluate(12.f, Max, Ref, RefYaw, On, Off);
	TestEqual(TEXT("noon elevation"), Noon.SunElevationDeg, Max, 1e-3f);

	const FCourtSkyState Night = FCourtSkyState::Evaluate(23.f, Max, Ref, RefYaw, On, Off);
	TestTrue(TEXT("moon at night"), Night.bMoon);
	TestTrue(TEXT("night light is dim but on (moon)"), Night.LightScale > 0.01f && Night.LightScale < 0.1f);
	TestEqual(TEXT("lamps full at night"), Night.LampScale, 1.f, 1e-4f);
	TestTrue(TEXT("lamps on after midnight"), FCourtSkyState::Evaluate(3.f, Max, Ref, RefYaw, On, Off).LampScale > 0.99f);
	TestTrue(TEXT("lamps fading in"), FMath::IsWithin(FCourtSkyState::Evaluate(18.6f, Max, Ref, RefYaw, On, Off).LampScale, 0.1f, 0.9f));
	TestEqual(TEXT("lamps off in the morning"), FCourtSkyState::Evaluate(7.f, Max, Ref, RefYaw, On, Off).LampScale, 0.f);

	// never lit from below, and the light changes smoothly across the day (no pops bigger than a few % per minute)
	float Prev = FCourtSkyState::Evaluate(0.f, Max, Ref, RefYaw, On, Off).LightScale;
	for (int32 m = 1; m < 24 * 60; ++m)
	{
		const FCourtSkyState S = FCourtSkyState::Evaluate(m / 60.f, Max, Ref, RefYaw, On, Off);
		if (S.LightPitchDeg > -1.f) { AddError(FString::Printf(TEXT("light from below at minute %d"), m)); break; }
		if (FMath::Abs(S.LightScale - Prev) > 0.05f) { AddError(FString::Printf(TEXT("light pops at minute %d"), m)); break; }
		Prev = S.LightScale;
	}
	return true;
}

#endif
