
const form = document.getElementById("ideaForm");
const submitBtn = document.getElementById("submitBtn");
const statusBox = document.getElementById("status");
const resultBox = document.getElementById("result");

const fields = [
    "idea_description",
    "industry",
    "target_customers",
    "relevant_details"
];

fields.forEach((name) => {
    const field = document.getElementById(name);

    field.addEventListener("input", () => {
        document.getElementById(`${name}_error`).textContent = "";
    });

    field.addEventListener("change", () => {
        document.getElementById(`${name}_error`).textContent = "";
    });
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    statusBox.textContent = "";
    resultBox.replaceChildren();
    resultBox.hidden = true;

    fields.forEach((name) => {
        document.getElementById(`${name}_error`).textContent = "";
    });

    const idea = {
        idea_description: document.getElementById("idea_description").value.trim(),
        industry: document.getElementById("industry").value.trim(),
        target_customers: document.getElementById("target_customers").value.trim(),
        relevant_details: document.getElementById("relevant_details").value.trim()
    };

    const errors = {};

    if (idea.idea_description.length < 20) {
        errors.idea_description = "Enter at least 20 characters.";
    }

    if (idea.idea_description.length > 5000) {
        errors.idea_description = "Maximum 5000 characters allowed.";
    }

    if (!idea.industry) {
        errors.industry = "Please select an industry.";
    }

    if (!idea.target_customers) {
        errors.target_customers = "Please enter your target customers.";
    }

    if (idea.target_customers.length > 500) {
        errors.target_customers = "Maximum 500 characters allowed.";
    }

    if (idea.relevant_details.length > 2000) {
        errors.relevant_details = "Maximum 2000 characters allowed.";
    }

    if (Object.keys(errors).length > 0) {
        Object.entries(errors).forEach(([name, message]) => {
            document.getElementById(`${name}_error`).textContent = message;
        });

        statusBox.textContent = "Please correct the highlighted fields.";
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";
    statusBox.textContent = "Sending your idea to the server...";

    try {
        const response = await fetch("/api/ideas", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(idea)
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            if (data.errors) {
                Object.entries(data.errors).forEach(([name, message]) => {
                    const errorElement = document.getElementById(`${name}_error`);
                    if (errorElement) {
                        errorElement.textContent = message;
                    }
                });
            }

            throw new Error(data.message || "Submission failed.");
        }

        statusBox.textContent = data.message;

        const heading = document.createElement("h3");
        heading.textContent = "Submitted Idea Details";

        const description = document.createElement("p");
        description.textContent = `Idea: ${data.idea.idea_description}`;

        const industry = document.createElement("p");
        industry.textContent = `Industry: ${data.idea.industry}`;

        const customers = document.createElement("p");
        customers.textContent = `Target Customers: ${data.idea.target_customers}`;

        const details = document.createElement("p");
        details.textContent = `Relevant Details: ${data.idea.relevant_details || "Not provided"}`;

        resultBox.append(heading, description, industry, customers, details);
        resultBox.hidden = false;

    } catch (error) {
        statusBox.textContent = `Error: ${error.message}`;
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit Startup Idea";
    }
});
