"""
ASTRA AI Orchestration Module

The orchestrator sits between the client request and the AI provider.
It is responsible for:
1. Receiving the OrchestratorRequest
2. Assembling context (memory, knowledge, conversation history)
3. Determining necessary tools
4. Formatting the AIRequest for the provider
5. Calling the provider
6. Executing tools if requested by the provider
7. Verifying the response (future)
8. Returning the OrchestratorResponse

It NEVER calls LLM APIs directly; it ALWAYS uses the AIProvider interface.
"""
