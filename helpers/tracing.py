import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from db.engine import db, myconext_db

class Telemetry(): 
    @staticmethod 
    def initialize(app, service_name : str, dev_mode : bool = False): 
        """ Sets up opentelemetry tracing and instruments LLM SDKs"""

        # 1 define the resource ( tags every span with app's name)
        resource = Resource(
            attributes = { 
                "service.name" : service_name,
                "environment" : "dev" if dev_mode else "production"
            }
        )

        provider = TracerProvider(resource = resource)

        #2 route spans based on the environment
        if dev_mode: 
          exporter = ConsoleSpanExporter()
        else: 
          exporter = OTLPSpanExporter()
        
        # 3 attach processor and register globally
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # 4 instrument external libraries
        # 1. LLM calls: ChatOpenAI and AsyncOpenAI both go through the openai SDK
        OpenAIInstrumentor().instrument()

        # 2. Outbound HTTP calls
        HTTPXClientInstrumentor().instrument()

        # 3. Database queries (async engines expose their sync engine for instrumentation)
        for engine in (db, myconext_db):
            SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

        # 4. Inbound FastAPI requests
        FastAPIInstrumentor.instrument_app(app)


        return trace.get_tracer(service_name)