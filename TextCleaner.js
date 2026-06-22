ObjC.import("Foundation");

var app = Application.currentApplication();
app.includeStandardAdditions = true;

var bundlePath = ObjC.unwrap($.NSBundle.mainBundle.bundlePath);
var projectRoot = ObjC.unwrap($(bundlePath).stringByDeletingLastPathComponent);
var pythonPath = projectRoot + "/.venv/bin/python";

function shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
}

function openDocuments(items) {
    var argumentsText = items.map(function (item) {
        return shellQuote(String(item));
    }).join(" ");
    var runnerPath = projectRoot + "/drag_cleaner.py";
    var outputPath = projectRoot + "/output/cleaned";

    if (!$.NSFileManager.defaultManager.fileExistsAtPath(pythonPath)) {
        app.displayDialog("尚未完成首次安装。\n请先双击“1_首次安装_macOS.command”。", {
            withTitle: "TextCleaner",
            buttons: ["确定"],
            defaultButton: "确定",
            withIcon: "caution"
        });
        return;
    }

    var commandText = shellQuote(pythonPath) + " " + shellQuote(runnerPath) + " " + argumentsText;
    try {
        var resultText = app.doShellScript(commandText);
        var dialog = app.displayDialog(resultText, {
            withTitle: "TextCleaner",
            buttons: ["完成", "打开输出文件夹"],
            defaultButton: "打开输出文件夹"
        });
        if (dialog.buttonReturned === "打开输出文件夹") {
            app.doShellScript("open " + shellQuote(outputPath));
        }
    } catch (error) {
        app.displayDialog("处理失败：\n" + error.message, {
            withTitle: "TextCleaner",
            buttons: ["确定"],
            defaultButton: "确定",
            withIcon: "stop"
        });
    }
}

function run() {
    app.displayDialog("请把 Markdown、PDF 或包含这些文件的文件夹拖到 TextCleaner 图标上。", {
        withTitle: "TextCleaner",
        buttons: ["确定"],
        defaultButton: "确定"
    });
}
