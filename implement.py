import transformers
import torch
import torch.nn.functional as F
import numpy as np
from sklearn.metrics import auc, roc_curve
from transformers import AutoModelForSequenceClassification, AutoTokenizer, AutoModelForCausalLM

# https://radar.vizhub.ai/

# Device setup for Apple M3 (MPS) or CUDA
device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# Load Vicuna for Local Paraphrasing
model_name = "lmsys/vicuna-7b-v1.5"
tokenizer_vicuna = AutoTokenizer.from_pretrained(model_name)
model_vicuna = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16).to(device)

# Load RADAR Detector and Tokenizer
def load_detector(model_path="TrustSafeAI/RADAR-Vicuna-7B"):
    detector = AutoModelForSequenceClassification.from_pretrained(model_path).to(device)
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    detector.eval()
    return detector, tokenizer

# Get AI-generated probability
def get_ai_probability(detector, tokenizer, texts):
    with torch.no_grad():
        inputs = tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
        output_probs = F.log_softmax(detector(**inputs).logits, -1)[:, 0].exp().tolist()
    return output_probs

# Local Vicuna-based Paraphraser
def paraphrase_with_vicuna(text, max_length=150):
    inputs = tokenizer_vicuna(f"Paraphrase the following sentence: {text}", return_tensors="pt").to(device)

    with torch.no_grad():
        output = model_vicuna.generate(
            **inputs,
            max_new_tokens=max_length,
            temperature=0.7,
            top_p=0.9,
            do_sample=True
        )

    return tokenizer_vicuna.decode(output[0], skip_special_tokens=True)

# Calculate ROC and Optimal Thresholds
def get_roc_metrics(human_preds, ai_preds):
    y_true = [0] * len(human_preds) + [1] * len(ai_preds)
    y_scores = human_preds + ai_preds
    fpr, tpr, thresholds = roc_curve(y_true, y_scores, pos_label=1)
    roc_auc = auc(fpr, tpr)

    # Optimal threshold: Youden's J statistic (maximize TPR - FPR)
    optimal_idx = np.argmax(tpr - fpr)
    optimal_threshold = thresholds[optimal_idx]

    return fpr.tolist(), tpr.tolist(), float(roc_auc), optimal_threshold

# Lambda Adjustment with Exponential Smoothing
def adjust_lambda(human_preds, ai_preds, target_fp_rate=0.05, current_lambda=0.5, alpha=0.3):
    _, _, _, optimal_threshold = get_roc_metrics(human_preds, ai_preds)
    false_positive_rate = sum([1 for p in human_preds if p > optimal_threshold]) / len(human_preds)

    # Dynamically adjust step size based on deviation from target
    step_size = min(0.1, abs(false_positive_rate - target_fp_rate))

    if false_positive_rate > target_fp_rate:
        new_lambda = max(0.1, current_lambda - step_size)
    else:
        new_lambda = min(1.0, current_lambda + step_size)

    # Apply exponential smoothing
    smoothed_lambda = alpha * new_lambda + (1 - alpha) * current_lambda

    return smoothed_lambda, optimal_threshold

# Classification without Review Threshold
def classify_text(prob, threshold=0.5):
    if prob < threshold:
        return "Human"
    else:
        return "AI"

# Example Usage
def main():
    # Initialize Detector and Tokenizer
    detector, tokenizer = load_detector()

    # Expanded Human and AI Texts Dataset
    human_texts = [
        "This is a human-generated text.",
        "The sun rise from the east and sets in the west.",
        "Education is the most powerful weapon if you want to change the world.",
        "Having a good health will give you the foundation of happiness.",
        "All great journies begin with a small single step."
    ]

    ai_texts = [
        "This sentence is generated by an AI model.",
        "The weather today is bright and sunny with a slight breeze.",
        "Artificial intelligence is transforming industries worldwide.",
        "Data-driven decision making enhances productivity.",
        "Quantum computing holds promise for complex problem-solving."
    ]

    # Get AI probabilities
    human_preds = get_ai_probability(detector, tokenizer, human_texts)
    ai_preds = get_ai_probability(detector, tokenizer, ai_texts)

    # Paraphrase AI Text using Vicuna
    paraphrased_ai_texts = [paraphrase_with_vicuna(text) for text in ai_texts]
    print(f"Paraphrased Text: {paraphrased_ai_texts}")

    paraphrased_ai_preds = get_ai_probability(detector, tokenizer, paraphrased_ai_texts)

    # Adjust Lambda using Exponential Smoothing
    lambda_value, optimal_threshold = adjust_lambda(human_preds, ai_preds)
    print(f"Adjusted Lambda (Smoothed): {lambda_value:.2f}, Optimal Threshold: {optimal_threshold:.3f}")

    # Classification without Review Mechanism
    for text, prob in zip(human_texts + ai_texts, human_preds + ai_preds):
        classification = classify_text(prob, threshold=optimal_threshold)
        print(f"Text: {text}\nProbability: {prob:.3f} → Classification: {classification}\n")

if __name__ == "__main__":
    main()
