import os
from dotenv import load_dotenv
from datetime import datetime
import json
import requests
import subprocess
from .SessionMemory import SessionMemory
from AI.API import settings
from AI.API.embeddings import DEFAULT_EMBEDDING_MODEL, create_embedding_model
import logging 

logger = logging.getLogger(__name__)
# Load environment variables from .env file
load_dotenv()


class Agent:
    """An OpenRouter-based AI Agent with tool calling capabilities and session memory."""
    
    def __init__(self, api_key: str = None, session_id: str = None, on_progress=None):
        """Initialize the Agent with OpenRouter API key and optional session ID.
        
        Args:
            api_key: OpenRouter API key
            session_id: Optional session ID for memory
        """
        if api_key is None:
            api_key = os.getenv("OPENROUTER_API_KEY", None)
        
        if api_key is None:
            raise ValueError(
                "OpenRouter API key not found. Please set the OPENROUTER_API_KEY environment variable "
                "or pass your API key directly."
            )
        
        self.openrouter_api_key = api_key
        self.tools = self._define_tools()
        self.session_id = session_id

        embedder_name = os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        llm_name = os.getenv("LLM")

        self._report_progress(on_progress, "embedding", "loading", embedder_name)
        try:
            embedding_model = self._create_embedding_model()
            self.session_memory = SessionMemory(embedding_model, session_id=session_id)
            self._report_progress(on_progress, "embedding", "ready", embedder_name)
        except Exception as exc:
            logger.warning("Could not initialize session memory: %s", exc)
            self.session_memory = None
            self._report_progress(
                on_progress,
                "embedding",
                "skipped",
                embedder_name,
                "Session memory is unavailable",
            )

        self._report_progress(on_progress, "llm", "ready", llm_name)
    
    @staticmethod
    def _report_progress(
        on_progress,
        component: str,
        state: str,
        model: str | None = None,
        message: str | None = None,
    ):
        if on_progress is None:
            return
        on_progress(component, state, model, message)
    
    def _create_embedding_model(self):
        """Create an embedding model based on environment configuration."""
        embedder_name = os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        return create_embedding_model(embedder_name)
    
    def _define_tools(self):
        """Define available tools for the agent."""
        return [
            {
                "name": "get_current_time",
                "description": "Get the current date and time",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "calculator",
                "description": "Perform basic math calculations",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["add", "subtract", "multiply", "divide"]
                        },
                        "a": {"type": "number"},
                        "b": {"type": "number"}
                    },
                    "required": ["operation", "a", "b"]
                }
            },
            {
                "name": "fetch_webpage",
                "description": "Fetch and retrieve content from a web page URL",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The full URL of the web page to fetch (e.g., https://example.com)"
                        }
                    },
                    "required": ["url"]
                }
            }
        ]
    
    def get_current_time(self):
        """Get the current date and time."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[TOOL CALLED] get_current_time() returned: {current_time}")
        return f"[TOOL RESULT] Current time is: {current_time}"

    def calculator(self, operation, a, b):
        """Perform basic math calculations."""
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                result = "Error: Division by zero"
            else:
                result = a / b
        else:
            result = "Error: Unknown operation"
        
        print(f"[TOOL CALLED] calculator({operation}, {a}, {b}) returned: {result}")
        return f"[TOOL RESULT] {a} {operation} {b} = {result}"

    def fetch_webpage(self, url):
        """Fetch content from a web page."""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            # Extract text content, limit to first 2000 characters
            content = response.text[:2000]
            print(f"[TOOL CALLED] fetch_webpage({url}) retrieved {len(response.text)} characters")
            return f"[TOOL RESULT] Successfully fetched {len(response.text)} characters from {url}\n\nContent preview:\n{content}..."
        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching {url}: {str(e)}"
            print(f"[TOOL CALLED] fetch_webpage({url}) failed: {error_msg}")
            return f"[TOOL RESULT] {error_msg}"

    def console(self, command):
        """Execute a terminal command and return the output."""
        try:
            print(f"[TOOL CALLED] console('{command}')")
            # Execute the command and capture output
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Combine stdout and stderr
            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]\n{result.stderr}"
            
            # Limit output to first 3000 characters
            output = output[:3000]
            
            print(f"[TOOL CALLED] console command executed with exit code: {result.returncode}")
            return f"[TOOL RESULT] Command executed with exit code {result.returncode}:\n{output}"
        
        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after 30 seconds"
            print(f"[TOOL CALLED] console command timed out")
            return f"[TOOL RESULT] {error_msg}"
        
        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            print(f"[TOOL CALLED] console command failed: {error_msg}")
            return f"[TOOL RESULT] {error_msg}"

    def execute_tool(self, tool_name, tool_input):
        """Execute a tool based on its name and input."""
        if tool_name == "get_current_time":
            return self.get_current_time()
        elif tool_name == "calculator":
            return self.calculator(**tool_input)
        elif tool_name == "fetch_webpage":
            return self.fetch_webpage(**tool_input)
        elif tool_name == "console":
            return self.console(**tool_input)
        else:
            return f"Error: Unknown tool {tool_name}"

    def query(self, user_message: str, session_id: str = None):
        """Run the agent interaction loop with tool calling using OpenRouter."""
        # Use provided session_id or default session memory
        if session_id:
            # Create or reuse session memory for this session
            if not hasattr(self, '_session_memories'):
                self._session_memories = {}
            
            if session_id not in self._session_memories:
                embedding_model = self._create_embedding_model()
                self._session_memories[session_id] = SessionMemory(embedding_model, session_id=session_id)
            
            session_mem = self._session_memories[session_id]
        else:
            session_mem = self.session_memory
        
        # Retrieve relevant conversation history and most recent message
        conversation_context = ""
        if session_mem:
            # Get the most recent message for immediate context
            most_recent = session_mem.get_most_recent_message()
            # Get related past conversations
            conversation_history = session_mem.retrieve_context(user_message, k=3, min_similarity=0.67)
            
            if most_recent:
                conversation_context = f"Most recent interaction:\n{most_recent}\n\n"
            if conversation_history:
                conversation_context += f"Related past interactions:\n{conversation_history}"
        
        # Build initial message with context if available
        if conversation_context:
            context_prefix = f"Conversation context:\n{conversation_context}\n\n"
            initial_content = context_prefix + user_message
        else:
            initial_content = user_message
        
        messages = [{"role": "user", "content": initial_content}]
        
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json"
        }
        
        ai_name = os.getenv("LLM", "meta-llama/llama-2-70b-chat")
        
        # Format tools for OpenRouter (OpenAI-compatible format)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"]
                }
            }
            for tool in self.tools
        ]
        
        while True:
            data = {
                "model": ai_name,
                "messages": messages,
                "tools": tools,
                "max_tokens": 1024,
            }
            
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            
            if response.status_code != 200:
                raise RuntimeError(f"OpenRouter API error: {response.text}")
            
            result = response.json()
            choice = result["choices"][0]
            
            # Check if model wants to call a tool
            if choice.get("finish_reason") == "tool_calls":
                assistant_message = choice["message"]
                messages.append({
                    "role": "assistant", 
                    "content": assistant_message.get("content", ""),
                    "tool_calls": assistant_message.get("tool_calls", [])
                })
                
                # Execute all tool calls
                tool_results = []
                for tool_call in assistant_message.get("tool_calls", []):
                    tool_name = tool_call["function"]["name"]
                    tool_input = json.loads(tool_call["function"]["arguments"])
                    tool_result = self.execute_tool(tool_name, tool_input)
                    
                    tool_results.append({
                        "tool_call_id": tool_call.get("id", ""),
                        "role": "tool",
                        "name": tool_name,
                        "content": str(tool_result)
                    })
                
                # Add tool results to messages
                messages.extend(tool_results)
            else:
                # Model generated final response
                final_response = choice["message"]["content"] if choice["message"].get("content") else "No response"
                
                # Store conversation in memory
                if session_mem:
                    session_mem.store_conversation(user_message, final_response)
                
                logger.info(f"{result}")
                return final_response, result['usage']

    def stream_query(self, question: str, session_id: str = None):
        """Agent mode does not stream: yield the finished answer as one piece."""
        reply, usage = self.query(question, session_id=session_id)
        yield reply
        return usage

    def update_embedding_model(self, embedding_name: str) -> dict:
        """
        Update the embedding model used for session memory.
        
        Args:
            embedding_name: Name of the new embedding model
            
        Returns:
            dict with status and message
        """
        try:
            # Create new embedding model
            new_embedder = self._create_embedding_model_by_name(embedding_name)
            
            # Update session memory embedder if it exists
            if self.session_memory:
                self.session_memory.embedding_model = new_embedder
            
            os.environ["EMBEDDING_MODEL"] = embedding_name
            return {
                "status": "success",
                "message": f"Embedding model updated to {embedding_name}",
                "embedding_model": embedding_name
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to update embedding model: {str(e)}",
                "embedding_model": None
            }

    def _create_embedding_model_by_name(self, embedding_name: str):
        """Create an embedding model by name."""
        return create_embedding_model(embedding_name)

    def update_llm(self, llm_name: str) -> dict:
        """
        Update the LLM model for the agent.
        
        Args:
            llm_name: Name of the new LLM model
            
        Returns:
            dict with status and message
        """
        try:
            # The agent uses Groq's LLM, so we just update the model name for future queries
            # This would typically be used to select different models like gpt-4, claude, etc.
            os.environ["LLM"] = llm_name
            return {
                "status": "success",
                "message": f"LLM model set to {llm_name} (will be used in next query)",
                "llm": llm_name
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to update LLM: {str(e)}",
                "llm": None
            }

    def get_current_config(self) -> dict:
        """
        Get the current agent configuration.
        
        Returns:
            dict with current settings
        """
        return {
            "embedding_model": os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
            "llm": os.getenv("LLM", "meta-llama/llama-2-70b-chat"),
            "provider": "openrouter"
        }
    
if __name__ == "__main__":
    # Initialize the agent
    agent = Agent()
    
    # Run the agent with a query
    result = agent.query("fetch https://example.com and summarise")
    print(result)