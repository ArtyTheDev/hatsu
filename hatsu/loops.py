import asyncio
import platform

try:
    import uvloop
except ImportError:
    uvloop = None

policies = {
    "uvloop": uvloop,
    "win32": asyncio
}
policies_classes = {
    "uvloop": "EventLoopPolicy",
    "win32": "WindowsSelectorEventLoopPolicy",
}

def set_event_loop_policy(policy: str) -> None:
    """To set the loop policy."""

    policy_mod = policies.get(policy, None)
    if policy_mod is None:
        raise ValueError(f"{policy} is not in (uvloop, win32)")

    policy_classes = getattr(
        policy_mod, policies_classes[policy]
    )

    if policy == "win32" and platform.platform() == "Windows":
        asyncio.set_event_loop_policy(policy_classes())
