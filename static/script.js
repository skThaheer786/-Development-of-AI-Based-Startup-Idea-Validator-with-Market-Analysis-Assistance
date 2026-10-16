
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("idea-form");

    const submitButton = document.getElementById("submit-idea-btn");
    const ideaStatus = document.getElementById("idea-status");
    const ideaResults = document.getElementById("idea-results");

    const marketButton = document.getElementById("search-market-btn");
    const marketStatus = document.getElementById("market-status");
    const marketResults = document.getElementById("market-results-list");

    const fullButton = document.getElementById("full-analysis-btn");
    const fullStatus = document.getElementById("full-analysis-status");
    const fullResults = document.getElementById("full-analysis-results");

    // Safely create elements without inserting untrusted HTML.
    function addText(parent, tag, text, className = "") {
        const element = document.createElement(tag);
        element.textContent = text ?? "";

        if (className) {
            element.className = className;
        }

        parent.appendChild(element);
        return element;
    }

    // Render nested JSON objects and arrays.
    function renderData(parent, data) {
        if (data === null || data === undefined) return;

        if (Array.isArray(data)) {
            const list = document.createElement("ul");

            data.forEach(item => {
                const li = document.createElement("li");

                if (item && typeof item === "object") {
                    renderData(li, item);
                } else {
                    li.textContent = String(item ?? "");
                }

                list.appendChild(li);
            });

            parent.appendChild(list);
            return;
        }

        if (typeof data !== "object") {
            addText(parent, "p", String(data));
            return;
        }

        Object.entries(data).forEach(([key, value]) => {
            const label = key
                .replace(/_/g, " ")
                .replace(/\b\w/g, char => char.toUpperCase());

            const section = document.createElement("div");
            section.className = "result-card";

            addText(section, "h4", label);
            renderData(section, value);

            parent.appendChild(section);
        });
    }

    // Read the current startup idea from the form.
    function getIdea() {
        const fields = new FormData(form);

        return {
            idea_description: String(
                fields.get("idea_description") || ""
            ).trim(),
            industry: String(
                fields.get("industry") || ""
            ).trim(),
            target_customers: String(
                fields.get("target_customers") || ""
            ).trim(),
            relevant_details: String(
                fields.get("relevant_details") || ""
            ).trim()
        };
    }

    // Validate required inputs before making API requests.
    function validateIdea(idea) {
        if (idea.idea_description.length < 20) {
            throw new Error(
                "Please enter an idea description of at least 20 characters."
            );
        }

        if (idea.idea_description.length > 5000) {
            throw new Error("Idea description is too long.");
        }

        if (!idea.industry) {
            throw new Error("Please enter the industry.");
        }

        if (!idea.target_customers) {
            throw new Error("Please enter your target customers.");
        }

        return idea;
    }

    // Send JSON to the Flask backend.
    async function postJSON(endpoint, payload) {
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        let data;

        try {
            data = await response.json();
        } catch {
            throw new Error("The server returned an invalid response.");
        }

        if (!response.ok || data.success === false) {
            throw new Error(
                data.error || `Request failed with status ${response.status}.`
            );
        }

        return data;
    }

    // Display individual web search results.
    function renderSearchResults(parent, research) {
        const queries = research.queries || [];
        const results = research.results || [];

        addText(parent, "h3", "Generated Search Queries");

        if (queries.length === 0) {
            addText(parent, "p", "No search queries were returned.");
        } else {
            const queryList = document.createElement("ul");

            queries.forEach(query => {
                addText(queryList, "li", query);
            });

            parent.appendChild(queryList);
        }

        addText(parent, "h3", "Market & Competitor Sources");

        if (results.length === 0) {
            addText(parent, "p", "No web sources were found.");
            return;
        }

        results.forEach((result, index) => {
            const card = document.createElement("article");
            card.className = "result-card";

            addText(
                card,
                "h3",
                `${index + 1}. ${result.title || "Untitled source"}`
            );

            addText(
                card,
                "p",
                result.content || "No summary available."
            );

            if (result.query) {
                addText(card, "p", `Search query: ${result.query}`);
            }

            if (result.url) {
                try {
                    const url = new URL(result.url);

                    if (url.protocol === "https:" || url.protocol === "http:") {
                        const link = document.createElement("a");
                        link.href = url.href;
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        link.textContent = "Read original source";

                        card.appendChild(link);
                    }
                } catch {
                    addText(card, "p", "Source URL is invalid.");
                }
            }

            parent.appendChild(card);
        });
    }

    // TASK 2: Groq structured idea extraction.
    form.addEventListener("submit", async event => {
        event.preventDefault();

        if (!form.reportValidity()) return;

        submitButton.disabled = true;
        ideaStatus.textContent = "Extracting startup idea...";
        ideaResults.replaceChildren();

        try {
            const idea = validateIdea(getIdea());
            const data = await postJSON("/api/ideas", idea);

            addText(ideaResults, "h3", "Structured Startup Idea");

            const result = data.extracted_idea ?? data.idea;

            if (result === undefined) {
                throw new Error(
                    "The server response did not contain extracted idea data."
                );
            }

            renderData(ideaResults, result);

            ideaStatus.textContent =
                data.message || "Idea extraction completed successfully.";

        } catch (error) {
            ideaStatus.textContent = error.message;
        } finally {
            submitButton.disabled = false;
        }
    });

    // TASK 3: Tavily market and competitor research.
    marketButton.addEventListener("click", async () => {
        if (!form.reportValidity()) return;

        marketButton.disabled = true;
        marketStatus.textContent = "Searching the market...";
        marketResults.replaceChildren();

        try {
            const idea = validateIdea(getIdea());
            const data = await postJSON("/api/market-search", idea);
            const research = data.market_research;

            if (!research || typeof research !== "object") {
                throw new Error("Invalid market research response.");
            }

            renderSearchResults(marketResults, research);

            marketStatus.textContent =
                `Market research completed. Found ${
                    research.total_results ?? (research.results || []).length
                } sources.`;

        } catch (error) {
            marketStatus.textContent = error.message;
        } finally {
            marketButton.disabled = false;
        }
    });

    // TASK 4 and TASK 5: Complete orchestrated workflow.
    fullButton.addEventListener("click", async () => {
        if (!form.reportValidity()) return;

        fullButton.disabled = true;
        fullStatus.textContent =
            "Running idea extraction and market research...";
        fullResults.replaceChildren();

        try {
            const idea = validateIdea(getIdea());
            const data = await postJSON("/api/orchestrate", idea);

            if (!data.structured_idea || !data.market_research) {
                throw new Error(
                    "The workflow response is missing required data."
                );
            }

            addText(fullResults, "h3", "Structured Startup Idea");
            renderData(fullResults, data.structured_idea);

            addText(fullResults, "h3", "Workflow Stages");

            const workflow = data.workflow || [];
            const workflowList = document.createElement("ol");

            workflow.forEach(stage => {
                addText(
                    workflowList,
                    "li",
                    String(stage).replace(/_/g, " ")
                );
            });

            fullResults.appendChild(workflowList);

            renderSearchResults(fullResults, data.market_research);

            fullStatus.textContent =
                `Full workflow completed successfully. ${
                    data.market_research.total_results ??
                    (data.market_research.results || []).length
                } market research sources retrieved.`;

        } catch (error) {
            fullStatus.textContent = error.message;
        } finally {
            fullButton.disabled = false;
        }
    });
});
