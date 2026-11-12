#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "LearningAgentsComparison.h"
#include "StreetballGym.h"
#include "StreetballWorld.h"
#include "MuJoCoSim.h"
#include "Components/ShapeComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "PhysicsEngine/PhysicsConstraintComponent.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FLAComparisonModelTest, "Streetball.LearningAgents.ModelAndReset",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FLAComparisonModelTest::RunTest(const FString&)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("LAComparisonTest"));
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	World->InitializeActorsForPlay(FURL());
	UMuJoCoSim* Definition = NewObject<UMuJoCoSim>(World);
	const bool bLoaded = Definition->LoadXml(Streetball::SceneXmlPath());
	TestTrue(TEXT("frozen model loads"), bLoaded);
	if (bLoaded)
	{
		ALAComparisonAgent* Agent = World->SpawnActor<ALAComparisonAgent>();
		const bool bInitialized = Agent->Initialize(Definition, FVector(5000, 0, 0), false);
		TestTrue(TEXT("Chaos model imports at a translated training origin"), bInitialized);
		if (bInitialized)
		{
			TestEqual(TEXT("all physical humanoid bodies imported"), Agent->Bodies.Num(), 15);
			TestEqual(TEXT("all actuator degrees of freedom imported"), Agent->Joints.Num(), 27);
			TestEqual(TEXT("all bodies except the free root are constrained"), Agent->Constraints.Num(), 14);
			TSet<int32> Actions;
			for (const FLAComparisonJoint& Joint : Agent->Joints) Actions.Add(Joint.LocalIndex);
			TestEqual(TEXT("actuator order is a one-to-one mapping"), Actions.Num(), 27);
			float Mass = 0;
			for (const FLAComparisonBody& Body : Agent->Bodies)
			{
				Mass += Body.Shape->GetMass();
				TestTrue(TEXT("Chaos body simulates"), Body.Shape->IsSimulatingPhysics());
				TestTrue(TEXT("Chaos mass matches frozen model"),
					FMath::IsNearlyEqual(Body.Shape->GetMass(), float(Definition->GetModel()->body_mass[Body.ModelBody]), 0.001f));
				if (Body.Constraint)
				{
					const FTransform Frame1 = Body.Constraint->ConstraintInstance.GetRefFrame(EConstraintFrame::Frame1)
						* Body.Shape->GetComponentTransform();
					const FTransform Frame2 = Body.Constraint->ConstraintInstance.GetRefFrame(EConstraintFrame::Frame2)
						* Agent->Bodies[Body.Parent].Shape->GetComponentTransform();
					UPrimitiveComponent* First = nullptr;
					UPrimitiveComponent* Second = nullptr;
					FName Bone1, Bone2;
					Body.Constraint->GetConstrainedComponents(First, Bone1, Second, Bone2);
					TestTrue(TEXT("Chaos receives child first and parent second"),
						First == Body.Shape && Second == Agent->Bodies[Body.Parent].Shape);
					TestTrue(TEXT("reset preserves coincident anatomical joint anchors"),
						FVector::Dist(Frame1.GetLocation(), Frame2.GetLocation()) < 0.1);
					if (Body.JointCount)
					{
						const FQuat Current = Frame2.GetRotation().Inverse() * Frame1.GetRotation();
						const FAngularDriveConstraint& Drive = Body.Constraint->ConstraintInstance.ProfileInstance.AngularDrive;
						TestTrue(TEXT("zero-action servo target matches the imported stand pose"),
							Current.AngularDistance(Drive.OrientationTarget.Quaternion()) < 0.002);
						TestFalse(TEXT("physical drives use torque, not mass-independent acceleration"), Drive.bAccelerationMode);
					}
				}
			}
			TestTrue(TEXT("humanoid mass is anatomical, not unit-mass defaults"), Mass > 70 && Mass < 90);
			TArray<float> Observation;
			Agent->Observe(Observation);
			TestEqual(TEXT("comparison preserves observation layout size"), Observation.Num(), 119);
			TestTrue(TEXT("root height remains metres, not centimetres"), Observation[101] > 0.8f && Observation[101] < 1.1f);
			TestTrue(TEXT("root position uses the translated environment origin"),
				Agent->BodyTransform(Agent->Pelvis).GetLocation().X > 4900);
			Agent->Angles[0] += 0.25f;
			Agent->Observe(Observation);
			TestTrue(TEXT("joint sensors are written in frozen actuator order"),
				FMath::IsNearlyEqual(Observation[9 + Agent->Joints[0].LocalIndex], 0.25f, 1e-5f));
			Agent->EpisodeTime = 3;
			Agent->EpisodeSteps = 150;
			Agent->ResetEpisode();
			TestEqual(TEXT("episode state resets without respawning"), Agent->EpisodeSteps, 0);
			TestEqual(TEXT("body pool retained across reset"), Agent->Bodies.Num(), 15);
			TestTrue(TEXT("reset clears velocities"), Agent->Bodies[Agent->Pelvis].Shape->GetPhysicsLinearVelocity().IsNearlyZero());
		}
		AStreetballCharacter* Original = World->SpawnActor<AStreetballCharacter>();
		TestFalse(TEXT("MuJoCo character still bypasses Chaos"), Original->Mesh->IsSimulatingPhysics());
		TestEqual(TEXT("MuJoCo character collision remains disabled"), Original->Mesh->GetCollisionEnabled(), ECollisionEnabled::NoCollision);
	}
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}
#endif
