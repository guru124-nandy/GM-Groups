document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".delete-btn").forEach((button) => {
        button.addEventListener("click", (event) => {
            const confirmed = window.confirm("Are you sure you want to delete this record?");
            if (!confirmed) {
                event.preventDefault();
            }
        });
    });

    const saveTestButton = document.querySelector("#save-test-btn");
    const saveStatus = document.querySelector("#save-status");

    if (saveTestButton) {
        saveTestButton.addEventListener("click", async () => {
            if (saveStatus) {
                saveStatus.textContent = "Sending data to server...";
            }

            try {
                const response = await fetch("http://127.0.0.1:5000/save", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        name: "test"
                    })
                });

                const result = await response.json();

                if (saveStatus) {
                    saveStatus.textContent = result.message || "Saved successfully";
                }
            } catch (error) {
                if (saveStatus) {
                    saveStatus.textContent = "Failed to connect to the server.";
                }
                console.error("Save request failed:", error);
            }
        });
    }
});
