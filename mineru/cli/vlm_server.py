# Copyright (c) Opendatalab. All rights reserved.
import click
import sys



def vllm_server():
    from mineru.model.vlm.vllm_server import main
    main()


def lmdeploy_server():
    from mineru.model.vlm.lmdeploy_server import main
    main()


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.option(
    '-e',
    '--engine',
    'inference_engine',
    type=click.Choice(['auto', 'vllm', 'lmdeploy']),
    default='auto',
    help='Select the inference engine used to accelerate VLM inference, default is "auto".',
)
@click.pass_context
def openai_server(ctx, inference_engine):
    sys.argv = [sys.argv[0]] + ctx.args
    if inference_engine == 'auto':
        from mineru.utils.engine_utils import get_vlm_engine

        selected_engine = get_vlm_engine('auto')
        if selected_engine == 'vllm-engine':
            inference_engine = 'vllm'
        elif selected_engine == 'lmdeploy-engine':
            inference_engine = 'lmdeploy'
        else:
            raise RuntimeError(
                f"VLM server does not support the selected engine: {selected_engine}"
            )

    if inference_engine == 'vllm':
        import vllm  # noqa: F401
        vllm_server()
    elif inference_engine == 'lmdeploy':
        import lmdeploy  # noqa: F401
        lmdeploy_server()

if __name__ == "__main__":
    openai_server()
