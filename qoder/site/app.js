const copyButton = document.querySelector("#copy-query");
const runCommand = document.querySelector("#run-command");

copyButton.addEventListener("click", async () => {
  const command = runCommand.textContent;
  try {
    await navigator.clipboard.writeText(command);
    copyButton.textContent = "已复制";
  } catch {
    const range = document.createRange();
    range.selectNodeContents(runCommand);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    copyButton.textContent = "已选中，请复制";
  }
  window.setTimeout(() => {
    copyButton.textContent = "复制运行命令";
  }, 1800);
});
