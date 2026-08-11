// Native fetch is available in Node 24
async function main() {
    console.log("=== FRONTEND STREAMING VERIFICATION ===");
    const startTime = Date.now();
    let ttft = null;
    let fullResponse = "";

    try {
        const response = await fetch('http://localhost:8000/api/conversation/message/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: "Say hello in exactly five words." })
        });

        if (!response.ok) {
            console.error(`HTTP Error: ${response.status}`);
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                const totalTime = Date.now() - startTime;
                console.log(`\n\n[DONE] Stream completed in: ${totalTime}ms`);
                break;
            }
            if (value) {
                if (ttft === null) {
                    ttft = Date.now() - startTime;
                    console.log(`\n[TTFT] First token received at: ${ttft}ms`);
                }
                const text = decoder.decode(value, { stream: true });
                fullResponse += text;
                process.stdout.write(text);
            }
        }

    } catch (e) {
        console.error("Error:", e);
    }
}

main();
