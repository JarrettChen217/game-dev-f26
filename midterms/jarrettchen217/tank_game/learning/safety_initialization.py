"""Explicit initialization for future matched358 SB3 policies; no training code."""


def zero_safety_columns(policy)->None:
    """Zero only added pi/vf input columns, leaving RNG/other weights untouched.

    H1 constructs untrained policies to verify function equality. It does not
    qualify a new training protocol or enable old340 checkpoint loaders for358.
    """
    import torch
    from stable_baselines3.common.torch_layers import FlattenExtractor

    if (policy.observation_space.shape!=(358,) or policy.action_space.n!=18
            or policy.net_arch!={'pi':[128,128],'vf':[128,128]}
            or type(policy.features_extractor) is not FlattenExtractor
            or policy.device.type!='cpu'):
        raise ValueError('requires CPU358/18 flat128x128 matched policy')
    layers=(policy.mlp_extractor.policy_net,policy.mlp_extractor.value_net)
    for net in layers:
        if (len(net)!=4 or type(net[0]) is not torch.nn.Linear
                or tuple(net[0].weight.shape)!=(128,358)
                or type(net[1]) is not torch.nn.Tanh
                or type(net[2]) is not torch.nn.Linear
                or tuple(net[2].weight.shape)!=(128,128)
                or type(net[3]) is not torch.nn.Tanh):
            raise ValueError('unsupported matched policy architecture')
    with torch.no_grad():
        for net in layers:
            net[0].weight[:,340:358].zero_()
