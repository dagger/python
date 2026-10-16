# dagger-pytest-otel

A pytest plugin for OpenTelemetry instrumentation with Dagger.

This plugin automatically instruments pytest tests with OpenTelemetry spans, enabling test visibility in Dagger's TUI and Dagger Cloud.

## Features

- **Zero configuration**: Automatically creates spans for each test
- **TRACEPARENT propagation**: Inherits trace context from Dagger
- **Session spans**: Creates a parent span for the entire test session
- **Test hierarchy**: Captures module, class, and function information
- **Outcome tracking**: Records test pass/fail/skip status
- **Log capture**: Forwards Python logs to OpenTelemetry
- **Exception recording**: Records test exceptions on spans

## Installation

```bash
pip install dagger-pytest-otel
```

## Usage

Once installed, the plugin is automatically enabled. No code changes are required in your tests.

### With Dagger

When running tests through Dagger, the `TRACEPARENT` environment variable is automatically set, and test spans will appear in the Dagger TUI and Dagger Cloud.

The [pytest module](https://github.com/dagger/python/tree/main/pytest) bundles this plugin. A module that builds its own test container installs it:

```python
# In your Dagger module
@function
async def test(self, source: dagger.Directory) -> str:
    return await (
        dag.container()
        .from_("python:3.11-slim")
        .with_directory("/src", source)
        .with_workdir("/src")
        .with_exec(["pip", "install", "pytest", "dagger-pytest-otel"])
        .with_exec(["pytest", "-v"])
        .stdout()
    )
```

### Standalone

You can also use the plugin standalone with any OTLP-compatible backend:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export TRACEPARENT="00-abc123...-def456...-01"  # Optional parent trace
pytest
```

The plugin sends OTLP over HTTP to an `http://` or `https://` endpoint, and over
gRPC to an endpoint without a scheme. `OTEL_EXPORTER_OTLP_PROTOCOL` (`grpc` or
`http/protobuf`) overrides that choice, and `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`
or `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` overrides it for one signal; any other
value sends `http/protobuf` with a warning. gRPC needs the
`opentelemetry-exporter-otlp-proto-grpc` package; without it, the plugin warns
and exports nothing.

### Disabling

To disable instrumentation:

```bash
pytest --no-otel
```

## Span Attributes

Each test span includes the following attributes:

| Attribute | Description |
|-----------|-------------|
| `dagger.io/ui.boundary` | Prevents log bubbling in Dagger TUI |
| `test.case.name` | Fully qualified pytest test case name |
| `test.case.result.status` | Test result (`pass`/`fail`/`skipped`) |
| `test.suite.name` | Pytest suite containing the test case |

Session spans also include `test.suite.run.status`. Their `test.suite.name` is
the pytest rootdir relative to the nearest directory holding `.git`, or the
rootdir's name at that directory or outside Git; 0.3.0 used the absolute path.

Spans and logs report the service name `pytest`, unless `OTEL_SERVICE_NAME` or
`OTEL_RESOURCE_ATTRIBUTES` sets one.

## Test output

Captured stdout and stderr output is exported as OpenTelemetry logs on the active
test span using Dagger's `stdio.stream` attribute. Python logging records are
also forwarded as OpenTelemetry logs and mapped to stdout or stderr by severity.

Python's root logger drops records below `WARNING` before the plugin sees them.
Set pytest's `log_level`, for example with `--log-level=INFO`, to forward
`INFO` records too.

## Development

```bash
cd pytest/dagger_pytest_otel
uv run pytest
```

## License

Apache-2.0
