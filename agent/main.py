from agent.v5_agent import agent_logic
from agent.ui import on_think_and_content, on_title, on_tool, on_end_message, on_start_message


on_think, on_content = on_think_and_content()

if __name__ == "__main__":

    final = agent_logic(
        user_message=input("Запрос: "),
        error_text="",
        on_think=on_think,
        on_content=on_content,
        on_title=on_title,
        on_tool=on_tool,
        on_end_message=on_end_message,
        on_start_message=on_start_message
    )
