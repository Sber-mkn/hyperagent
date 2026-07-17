def stylesheet(theme: str = "dark") -> str:
    if theme == "light":
        return """
    QMainWindow, QStackedWidget, QWidget {
        background: #f4f6f8;
        color: #20242b;
        font-family: "Inter", "Segoe UI", sans-serif;
        font-size: 14px;
    }

    QLabel {
        background: transparent;
    }

    #topBar {
        background: #ffffff;
        border-bottom: 1px solid #d9dde5;
    }

    #screenTitle, #loginTitle {
        color: #151922;
        font-weight: 650;
    }

    #screenTitle {
        font-size: 16px;
    }

    #loginTitle {
        font-size: 24px;
    }

    #loginSubtitle, #mutedLabel {
        color: #69717d;
    }

    #loginPanel, #settingsPanel {
        background: #ffffff;
        border: 1px solid #d7dce4;
        border-radius: 8px;
    }

    #settingsBody, #chatBody, #agentScroll, #agentOutput {
        background: #f4f6f8;
    }

    #settingsSectionTitle {
        color: #151922;
        font-size: 15px;
        font-weight: 700;
        padding-top: 4px;
    }

    #settingsRadio {
        color: #252b34;
        padding: 4px 0;
    }

    #inputLabel {
        color: #616a76;
        font-size: 12px;
        font-weight: 600;
        padding-left: 2px;
    }

    #errorLabel {
        color: #c23838;
    }

    QLineEdit, QPlainTextEdit {
        background: #ffffff;
        color: #151922;
        border: 1px solid #cfd5df;
        border-radius: 6px;
        padding: 8px;
        selection-background-color: #2f68d8;
    }

    QLineEdit:focus, QPlainTextEdit:focus {
        border-color: #2f78ff;
    }

    #primaryButton {
        background: #2f68d8;
        color: #ffffff;
        border: 0;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 600;
    }

    #flatButton, #ghostButton, #menuButton, #selectorButton {
        background: transparent;
        color: #252b34;
        border: 0;
        border-radius: 6px;
        padding: 6px 8px;
    }

    #flatButton:hover, #ghostButton:hover, #menuButton:hover, #selectorButton:hover {
        background: #e8ebf0;
    }

    #modelMenuList {
        background: #ffffff;
        color: #252b34;
        border: 0;
        outline: 0;
    }

    #modelMenuList::item {
        padding: 7px 10px;
    }

    #modelMenuList::item:selected {
        background: #e8eefc;
    }

    #flatButton:disabled {
        color: #a0a7b1;
        background: transparent;
    }

    #menuButton {
        font-size: 22px;
        padding: 2px 8px;
    }

    QMenu {
        background: #ffffff;
        color: #1f2630;
        border: 1px solid #d6dbe3;
        padding: 4px;
    }

    QMenu::item {
        padding: 7px 24px 7px 10px;
        border-radius: 4px;
    }

    QMenu::item:selected {
        background: #e8eefc;
    }

    #chatList {
        background: #f4f6f8;
        border: 0;
        outline: 0;
        padding: 8px;
    }

    #chatList::item {
        min-height: 52px;
        color: #252b34;
        border-radius: 6px;
        padding: 7px 9px;
    }

    #chatList::item:hover {
        background: #e9edf3;
    }

    #chatList::item:selected {
        background: #dce8ff;
    }

    #userMessage {
        background: #dce8ff;
        color: #101722;
        border: 1px solid #9ebeff;
        border-radius: 7px;
        padding: 10px 12px;
    }

    #assistantText {
        color: #252b34;
        font-size: 14px;
        line-height: 1.35;
        padding: 2px 0;
    }

    #modelHeader {
        color: #151922;
        font-size: 15px;
        font-weight: 700;
        padding: 2px 0 0 0;
    }

    #statusMessage, #resultMessage {
        color: #596270;
        background: #ffffff;
        border: 1px solid #d7dce4;
        border-radius: 7px;
        padding: 8px 10px;
    }

    #waitingMessage {
        color: #727b88;
        padding: 2px 0 6px 0;
    }

    #commandBlock {
        background: #ffffff;
        border: 1px solid #d7dce4;
        border-radius: 8px;
    }

    #commandIcon, #commandTitle, #commandText {
        color: #252b34;
    }

    #commandIcon {
        border: 1px solid #8d94a1;
        border-radius: 3px;
        padding: 0 3px;
        font-size: 10px;
        font-weight: 700;
    }

    #commandTitle {
        font-size: 13px;
        font-weight: 650;
    }

    #commandWaiting, #commandDone {
        color: #727b88;
        font-size: 14px;
        padding: 2px 0;
    }

    #commandFailed {
        color: #c23838;
        font-size: 14px;
        padding: 2px 0;
    }

    #commandDetails, #collapsibleBlock {
        background: transparent;
    }

    #commandDetailsText {
        color: #596270;
        font-family: "JetBrains Mono", "Consolas", monospace;
        font-size: 12px;
        line-height: 1.3;
    }

    #collapsibleHeader {
        color: #596270;
        border: 0;
        padding: 0;
        font-size: 13px;
        font-weight: 600;
    }

    #collapsibleHeader:hover {
        color: #252b34;
        text-decoration: underline;
    }

    #collapsibleBody {
        background: #ffffff;
        border-left: 2px solid #d7dce4;
        padding: 0;
    }

    #thinkText {
        color: #69717d;
        line-height: 1.35;
    }

    #inputFrame {
        background: #ffffff;
        border: 2px solid #2f68d8;
        border-radius: 8px;
    }

    #taskInput {
        border: 0;
        background: #ffffff;
        color: #151922;
        padding: 2px;
    }

    #sendButton {
        background: transparent;
        color: #252b34;
        border: 0;
        border-radius: 6px;
        font-size: 21px;
        font-weight: 650;
    }

    #sendButton:hover {
        background: #e8ebf0;
    }

    #sendButton:disabled {
        color: #a0a7b1;
    }
    """
    return """
    QMainWindow, QStackedWidget, QWidget {
        background: #18191b;
        color: #d6d8de;
        font-family: "Inter", "Segoe UI", sans-serif;
        font-size: 14px;
    }

    QLabel {
        background: transparent;
    }

    #topBar {
        background: #18191b;
        border-bottom: 1px solid #25272b;
    }

    #screenTitle {
        color: #f1f3f7;
        font-size: 16px;
        font-weight: 620;
    }

    #mutedLabel {
        color: #858a94;
    }

    #settingsBody {
        background: #18191b;
    }

    #settingsPanel {
        background: #202226;
        border: 1px solid #333742;
        border-radius: 8px;
    }

    #settingsSectionTitle {
        color: #f1f3f7;
        font-size: 15px;
        font-weight: 700;
        padding-top: 4px;
    }

    #settingsRadio {
        color: #d8dbe2;
        padding: 4px 0;
    }

    #loginPanel {
        background: #202226;
        border: 1px solid #333742;
        border-radius: 8px;
    }

    #loginTitle {
        color: #f1f3f7;
        font-size: 24px;
        font-weight: 650;
    }

    #loginSubtitle {
        color: #9298a5;
        font-size: 13px;
    }

    #inputLabel {
        color: #9ba1ad;
        font-size: 12px;
        font-weight: 600;
        padding-left: 2px;
    }

    #errorLabel {
        color: #ff8f8f;
    }

    QLineEdit, QPlainTextEdit {
        background: #18191b;
        color: #eef0f5;
        border: 1px solid #383b42;
        border-radius: 6px;
        padding: 8px;
        selection-background-color: #2f68d8;
    }

    QLineEdit:focus, QPlainTextEdit:focus {
        border-color: #2f78ff;
    }

    #primaryButton {
        background: #2f78ff;
        color: #ffffff;
        border: 0;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 600;
    }

    #primaryButton:hover {
        background: #4084ff;
    }

    #primaryButton:disabled {
        background: #31343a;
        color: #777d88;
    }

    #flatButton, #ghostButton, #menuButton, #selectorButton {
        background: transparent;
        color: #d8dbe2;
        border: 0;
        border-radius: 6px;
        padding: 6px 8px;
    }

    #flatButton:hover, #ghostButton:hover, #menuButton:hover, #selectorButton:hover {
        background: #27292e;
    }

    #modelMenuList {
        background: #222327;
        color: #e8eaf0;
        border: 0;
        outline: 0;
    }

    #modelMenuList::item {
        padding: 7px 10px;
    }

    #modelMenuList::item:selected {
        background: #30343a;
    }

    #flatButton:disabled {
        color: #686d77;
        background: transparent;
    }

    #menuButton {
        font-size: 22px;
        padding: 2px 8px;
    }

    QMenu {
        background: #222327;
        color: #e8eaf0;
        border: 1px solid #343740;
        padding: 4px;
    }

    QMenu::item {
        padding: 7px 24px 7px 10px;
        border-radius: 4px;
    }

    QMenu::item:selected {
        background: #30343a;
    }

    #chatList {
        background: #18191b;
        border: 0;
        outline: 0;
        padding: 8px;
    }

    #chatList::item {
        min-height: 52px;
        color: #d9dce3;
        border-radius: 6px;
        padding: 7px 9px;
    }

    #chatList::item:hover {
        background: #24262b;
    }

    #chatList::item:selected {
        background: #26344f;
    }

    #chatBody {
        background: #18191b;
    }

    #agentScroll {
        background: #18191b;
        border: 0;
        padding: 0;
    }

    #agentOutput {
        background: #18191b;
        color: #d6d8de;
    }

    #userMessage {
        background: #253b5d;
        color: #f0f2f6;
        border: 1px solid #3f6fb6;
        border-radius: 7px;
        padding: 10px 12px;
    }

    #assistantText {
        color: #e1e3e8;
        font-size: 14px;
        line-height: 1.35;
        padding: 2px 0;
    }

    #modelHeader {
        color: #f0f2f6;
        font-size: 15px;
        font-weight: 700;
        padding: 2px 0 0 0;
    }

    #statusMessage, #resultMessage {
        color: #aeb3bd;
        background: #1e2024;
        border: 1px solid #2c2f36;
        border-radius: 7px;
        padding: 8px 10px;
    }

    #waitingMessage {
        color: #858b96;
        padding: 2px 0 6px 0;
    }

    #commandBlock {
        background: #1b1d20;
        border: 1px solid #383c45;
        border-radius: 8px;
    }

    #commandIcon {
        color: #d7dbe3;
        border: 1px solid #8d94a1;
        border-radius: 3px;
        padding: 0 3px;
        font-size: 10px;
        font-weight: 700;
    }

    #commandTitle {
        color: #d7dbe3;
        font-size: 13px;
        font-weight: 650;
    }

    #commandText {
        color: #d7dbe3;
        font-size: 14px;
        padding: 2px 0;
    }

    #commandWaiting {
        color: #858b96;
        font-size: 14px;
        padding: 2px 0;
    }

    #commandDone {
        color: #858b96;
        font-size: 14px;
        padding: 2px 0;
    }

    #commandFailed {
        color: #ff9a9a;
        font-size: 14px;
        padding: 2px 0;
    }

    #commandDetails {
        background: transparent;
    }

    #commandDetailsText {
        color: #aeb3bd;
        font-family: "JetBrains Mono", "Consolas", monospace;
        font-size: 12px;
        line-height: 1.3;
    }

    #collapsibleBlock {
        background: transparent;
    }

    #collapsibleHeader {
        color: #9ca2ad;
        border: 0;
        padding: 0;
        font-size: 13px;
        font-weight: 600;
    }

    #collapsibleHeader:hover {
        color: #c0c5ce;
        text-decoration: underline;
    }

    #collapsibleBody {
        background: #1b1c1f;
        border-left: 2px solid #343841;
        padding: 0;
    }

    #thinkText {
        color: #a2a7b0;
        line-height: 1.35;
    }

    #inputFrame {
        background: #1b1c1f;
        border: 2px solid #2f78ff;
        border-radius: 8px;
    }

    #taskInput {
        border: 0;
        background: #1b1c1f;
        color: #e7e9ef;
        padding: 2px;
    }

    #sendButton {
        background: transparent;
        color: #dfe6f5;
        border: 0;
        border-radius: 6px;
        font-size: 21px;
        font-weight: 650;
    }

    #sendButton:hover {
        background: #2a2d33;
    }

    #sendButton:disabled {
        color: #616671;
    }

    QScrollBar:vertical {
        background: #18191b;
        width: 9px;
    }

    QScrollBar::handle:vertical {
        background: #4b4f58;
        border-radius: 4px;
        min-height: 28px;
    }

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {
        height: 0;
    }
    """
