"""Tests for the config module."""

import os
import sys
import types

import pytest

GRPC_EXPORTERS = (
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.exporter.otlp.proto.grpc._log_exporter",
)


class _GrpcExporter:
    pass


@pytest.fixture
def with_grpc(monkeypatch):
    """A stand-in for the optional gRPC exporter package."""
    fake = types.SimpleNamespace(OTLPSpanExporter=_GrpcExporter, OTLPLogExporter=_GrpcExporter)
    for name in GRPC_EXPORTERS:
        monkeypatch.setitem(sys.modules, name, fake)


@pytest.fixture
def without_grpc(monkeypatch):
    """The optional gRPC exporter package missing, whether or not it is installed."""
    for name in GRPC_EXPORTERS:
        monkeypatch.setitem(sys.modules, name, None)


class TestTelemetryConfig:
    """Tests for TelemetryConfig."""

    def test_singleton(self):
        """Verify TelemetryConfig is a singleton."""
        from dagger_pytest_otel.config import TelemetryConfig

        config1 = TelemetryConfig()
        config2 = TelemetryConfig()

        assert config1 is config2

    def test_configure_extracts_traceparent(
        self, monkeypatch, reset_telemetry, mock_otlp_exporters, with_traceparent
    ):
        """Test that configure extracts TRACEPARENT from environment."""
        from dagger_pytest_otel.config import TelemetryConfig

        config = TelemetryConfig()
        config._is_configured = False  # Reset state
        config.configure()

        # Verify configuration completed without error
        assert config._is_configured

        # Verify TRACEPARENT was present in environment
        assert with_traceparent == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

    def test_configure_without_traceparent(
        self, monkeypatch, reset_telemetry, mock_otlp_exporters
    ):
        """Test configuration without TRACEPARENT."""
        from dagger_pytest_otel.config import TelemetryConfig

        monkeypatch.delenv("TRACEPARENT", raising=False)

        config = TelemetryConfig()
        config._is_configured = False
        config.configure()

        # Should complete without error
        assert config._is_configured

    def test_configure_idempotent(self, reset_telemetry, mock_otlp_exporters):
        """Test that configure is idempotent."""
        from dagger_pytest_otel.config import TelemetryConfig

        config = TelemetryConfig()
        config._is_configured = False

        config.configure()
        first_provider = config._tracer_provider

        config.configure()
        second_provider = config._tracer_provider

        # Should not create a new provider
        assert first_provider is second_provider

    def test_get_tracer_auto_configures(self, reset_telemetry, mock_otlp_exporters):
        """Test that get_tracer automatically configures telemetry."""
        from dagger_pytest_otel.config import TelemetryConfig

        config = TelemetryConfig()
        config._is_configured = False

        tracer = config.get_tracer()

        assert config._is_configured
        assert tracer is not None

    def test_prepare_env_derives_logs_endpoint(self, monkeypatch, reset_telemetry):
        """Test logs endpoint is derived from a trace-specific endpoint."""
        from dagger_pytest_otel.config import TelemetryConfig

        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", raising=False)
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "http://127.0.0.1:4318/v1/traces",
        )
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "http/protobuf")

        TelemetryConfig()._prepare_env()

        assert (
            os.environ["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"]
            == "http://127.0.0.1:4318/v1/logs"
        )
        assert os.environ["OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"] == "http/protobuf"

    def test_prepare_env_preserves_generic_endpoint(self, monkeypatch, reset_telemetry):
        """Test generic OTLP endpoint handling is left to exporters."""
        from dagger_pytest_otel.config import TelemetryConfig

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "http://127.0.0.1:4318/v1/traces",
        )
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", raising=False)

        TelemetryConfig()._prepare_env()

        assert "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT" not in os.environ


class TestServiceName:
    """Without a service name, a trace backend files every run under unknown_service."""

    def test_defaults_to_pytest(self, no_otel_env):
        from dagger_pytest_otel.config import _resource

        assert _resource().attributes["service.name"] == "pytest"

    def test_otel_service_name_wins(self, monkeypatch, no_otel_env):
        from dagger_pytest_otel.config import _resource

        monkeypatch.setenv("OTEL_SERVICE_NAME", "checkout-tests")

        assert _resource().attributes["service.name"] == "checkout-tests"

    def test_resource_attributes_win(self, monkeypatch, no_otel_env):
        from dagger_pytest_otel.config import _resource

        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=billing,team=qa")

        attributes = _resource().attributes
        assert attributes["service.name"] == "billing"
        assert attributes["team"] == "qa"

    def test_otel_service_name_beats_resource_attributes(self, monkeypatch, no_otel_env):
        from dagger_pytest_otel.config import _resource

        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=billing")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "checkout-tests")

        assert _resource().attributes["service.name"] == "checkout-tests"

    def test_spans_and_logs_carry_it(self, reset_telemetry, mock_otlp_exporters, no_otel_env):
        from dagger_pytest_otel.config import TelemetryConfig

        config = TelemetryConfig()
        config.configure()

        assert config._tracer_provider.resource.attributes["service.name"] == "pytest"
        assert config._logger_provider.resource.attributes["service.name"] == "pytest"


class TestProtocol:
    """OTEL_EXPORTER_OTLP_*_PROTOCOL chooses the transport, and a missing one says so."""

    def test_an_http_endpoint_uses_http(self, monkeypatch, no_otel_env):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        from dagger_pytest_otel.config import _get_otlp_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")

        assert isinstance(_get_otlp_exporter(), OTLPSpanExporter)

    def test_an_endpoint_without_a_scheme_uses_grpc(self, monkeypatch, no_otel_env, with_grpc):
        from dagger_pytest_otel.config import _get_otlp_exporter, _get_otlp_log_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")

        assert isinstance(_get_otlp_exporter(), _GrpcExporter)
        assert isinstance(_get_otlp_log_exporter(), _GrpcExporter)

    def test_the_protocol_variable_wins_over_the_scheme(self, monkeypatch, no_otel_env, with_grpc):
        from dagger_pytest_otel.config import _get_otlp_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")

        assert isinstance(_get_otlp_exporter(), _GrpcExporter)

    def test_the_signal_protocol_wins_over_the_generic_one(self, monkeypatch, no_otel_env):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        from dagger_pytest_otel.config import _get_otlp_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "http/protobuf")

        assert isinstance(_get_otlp_exporter(), OTLPSpanExporter)

    def test_a_missing_grpc_exporter_says_how_to_fix_it(
        self, monkeypatch, no_otel_env, without_grpc, caplog
    ):
        from dagger_pytest_otel.config import _get_otlp_exporter, _get_otlp_log_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")

        assert _get_otlp_exporter() is None
        assert _get_otlp_log_exporter() is None
        assert "opentelemetry-exporter-otlp-proto-grpc" in caplog.text
        assert "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf" in caplog.text
        assert "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf" in caplog.text

    def test_an_unsupported_protocol_falls_back_to_http(self, monkeypatch, no_otel_env, caplog):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        from dagger_pytest_otel.config import _get_otlp_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/json")

        assert isinstance(_get_otlp_exporter(), OTLPSpanExporter)
        assert "http/json" in caplog.text

    def test_a_traces_protocol_leaves_logs_on_the_generic_one(self, monkeypatch, no_otel_env):
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

        from dagger_pytest_otel.config import TelemetryConfig, _get_otlp_log_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://127.0.0.1:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "grpc")

        TelemetryConfig()._prepare_env()

        assert isinstance(_get_otlp_log_exporter(), OTLPLogExporter)

    def test_logs_follow_the_logs_protocol(self, monkeypatch, no_otel_env):
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

        from dagger_pytest_otel.config import _get_otlp_log_exporter

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/protobuf")

        assert isinstance(_get_otlp_log_exporter(), OTLPLogExporter)
