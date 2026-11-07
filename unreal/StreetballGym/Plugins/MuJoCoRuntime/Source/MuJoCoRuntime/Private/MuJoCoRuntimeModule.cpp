#include "Modules/ModuleManager.h"
#include "Interfaces/IPluginManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/Paths.h"
#include "MuJoCoSim.h"

DEFINE_LOG_CATEGORY(LogMuJoCo);

class FMuJoCoRuntimeModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		// mujoco.dll is delay-loaded; resolve it from the plugin's ThirdParty/bin (or next to the
		// executable, where RuntimeDependencies stages it for packaged builds).
		const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("MuJoCoRuntime"));
		FString DllPath;
		if (Plugin.IsValid())
		{
			DllPath = FPaths::Combine(Plugin->GetBaseDir(), TEXT("ThirdParty/mujoco/bin/mujoco.dll"));
		}
		if (DllPath.IsEmpty() || !FPaths::FileExists(DllPath))
		{
			DllPath = FPaths::Combine(FPlatformProcess::BaseDir(), TEXT("mujoco.dll"));
		}
		DllHandle = FPlatformProcess::GetDllHandle(*DllPath);
		if (!DllHandle)
		{
			UE_LOG(LogMuJoCo, Error, TEXT("Failed to load mujoco.dll from %s"), *DllPath);
		}
		else
		{
			UE_LOG(LogMuJoCo, Log, TEXT("Loaded %s (header %d, library %d)"), *DllPath, mjVERSION_HEADER, mj_version());
			if (mj_version() != mjVERSION_HEADER)
			{
				UE_LOG(LogMuJoCo, Error, TEXT("mujoco.dll version %d does not match header %d"), mj_version(), mjVERSION_HEADER);
			}
		}
	}

	virtual void ShutdownModule() override
	{
		if (DllHandle)
		{
			FPlatformProcess::FreeDllHandle(DllHandle);
			DllHandle = nullptr;
		}
	}

private:
	void* DllHandle = nullptr;
};

IMPLEMENT_MODULE(FMuJoCoRuntimeModule, MuJoCoRuntime)
