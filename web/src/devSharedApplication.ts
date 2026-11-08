import { createAccountContext } from "./accountContext";
import { DevSharedProjectRepository } from "./devSharedProjectRepository";
import type { PlatformCapabilities } from "./platform";

export function createDevSharedApplication(platform: PlatformCapabilities) {
  const session = platform.session.storage;
  const sharedPlatform: PlatformCapabilities = { ...platform,
    session: { ...platform.session, storage: {
      getItem: key => session.getItem(`dev-shared.${key}`),
      setItem: (key, value) => session.setItem(`dev-shared.${key}`, value),
      removeItem: key => session.removeItem(`dev-shared.${key}`),
    } },
    persistence: { ...platform.persistence,
      createProjectRepository: (validate, context) => {
        if (!context || context.account_id) throw new Error("Dev storage requires an anonymous context");
        return new DevSharedProjectRepository(validate,
          platform.persistence.createProjectRepository(validate, context), platform.persistence.values, context);
      },
    },
  };
  // No Firebase initialization, account adoption, deletion or cloud synchronization.
  return createAccountContext(sharedPlatform);
}
