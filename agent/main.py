import sys
import traceback

AGENT_ERROR_LOG = "/logs/agent_error.log"

def main():
    pass

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        with open(AGENT_ERROR_LOG, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        sys.exit(1)
