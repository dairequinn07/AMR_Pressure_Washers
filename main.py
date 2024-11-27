import os
import pandas as pd
from flask import Flask, render_template, request, make_response, redirect, jsonify, session, url_for, flash, abort
from square.client import Client
from square.http.auth.o_auth_2 import BearerAuthCredentials

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

# Load the Excel file once
EXCEL_FILE = 'products.xlsx'
products_df = pd.read_excel(EXCEL_FILE)


client = Client(bearer_auth_credentials=BearerAuthCredentials(access_token=os.environ['SQUARE_ACCESS_TOKEN']),
                environment='sandbox')


# Step 3: Add HTTPS redirection before any request is processed
@app.before_request
def https_redirect():
    if not request.is_secure and request.headers.get('x-forwarded-proto') != 'https':
        # Redirect HTTP requests to HTTPS
        return redirect(request.url.replace('http://', 'https://', 1), code=301)


@app.before_request
def initialize_cart():
    if 'cart' not in session:
        session['cart'] = []


@app.after_request
def add_response_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response


def create_payment_link():
    data = request.get_json()
    delivery_option = data.get('deliveryOption', 'pickup')  # Default to 'pickup' if not provided
    # Get cart items from session
    cart = session.get('cart', [])

    # Create line items dynamically from the cart
    line_items = []
    for item in cart:
        line_items.append({
            'name': item['Name'],  # Product name
            'quantity': str(item['Quantity']),  # Quantity must be a string
            'base_price_money': {
                'amount': int(item['Price'] * 100),  # Square expects amount in the smallest currency unit
                'currency': 'GBP'  # Adjust to your store's currency
            }
        })

    # Add delivery fee if selected
    if delivery_option == 'delivery':
        line_items.append({
            'name': 'Delivery Fee',
            'quantity': '1',
            'base_price_money': {
                'amount': 3000, # £30.00
                'currency': 'GBP',
            },
        })

    # Generate the payment link using Square's Checkout API
    response = client.checkout.create_payment_link(
        body={
            "order": {
                "location_id": "LS1HEYMHR59Q5",  # Replace with your actual location ID
                "line_items": line_items,  # Use dynamically created line items
            },
            "checkout_options": {
                "redirect_url": url_for('checkout_success', _external=True),  # Redirect after successful payment
                "ask_for_shipping_address": (delivery_option == 'delivery'), # collect shipping details for delivery
            }
        }
    )

    # Handle the API response
    if response.is_success():
        return response.body['payment_link']  # Return the payment link
    else:
        # Print errors for debugging
        print("Error creating payment link:", response.errors)
        return None


@app.route('/create-checkout-link', methods=['POST'])
def generate_checkout():
    payment_link = create_payment_link()
    if payment_link:
        return jsonify({'payment_link': payment_link['url']}), 200
    else:
        return jsonify({'error': 'Unable to generate payment link'}), 500


@app.context_processor
def inject_cart():
    # Pass the cart and its length to all templates
    cart = session.get('cart', [])
    return dict(cart_length=len(cart))  # Inject cart length into the context


@app.route('/checkout-success', methods=['GET'])
def checkout_success():
    # Example session data
    cart = session.get('cart', [])
    delivery_option = session.get('deliveryOption', 'pickup')
    total_amount = session.get('totalAmount', 0)  # Total including delivery if applicable

    return render_template(
        'payment_summary.html',
        cart=cart,
        delivery_option=delivery_option,
        total_amount=total_amount
    )


@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    product = request.get_json()  # Get the product data from the request
    product_id = int(product['ID'])

    # Initialize the cart in session if it doesn't exist
    if 'cart' not in session:
        session['cart'] = []

    # Check if the product already exists in the cart
    cart = session['cart']
    existing_item = next((item for item in cart if item['ID'] == product_id), None)

    if existing_item:
        # If product already in cart, increase the quantity
        existing_item['Quantity'] += 1
    else:
        # Add the new product to the cart with quantity 1
        product['Quantity'] = 1
        product['Price'] = float(product['Price'])
        cart.append(product)

    # Save the updated cart to the session
    session['cart'] = cart

    # Return the updated cart length and items to update the frontend
    return jsonify({
        'cart_length': len(cart),
        'cart_items': cart  # Sending back the entire cart to update the UI
    })


@app.template_filter('sum')
def sum_filter(cart, attribute, attr=None):
    if attr:
        return sum(float(item[attribute]) * int(item[attr]) for item in cart)
    return sum(float(item[attribute]) for item in cart)


@app.route('/product/<int:product_id>')
def product_page(product_id):
    # Fetch the row matching the product_id
    product_row = products_df.iloc[product_id - 1]  # Adjust for 0-indexing
    product = {
        'ID': product_id,
        'Name': product_row['Name'],
        'Price': product_row['Price'],
        'Description': product_row['Description'],
        'ImageURLs': product_row['ImageURLs'],
        # 'Features': product_row['Features'].split('\n')  # Assume features are newline-separated
        'Stock': product_row['Stock'],
    }
    return render_template('productPage.html', product=product)


@app.route('/PetrolPowered')
def PetrolPowered():
    products = products_df[products_df['Department'] == 'Petrol Washer'].to_dict(orient='records')
    return render_template('petrolWashers.html', products=products)


@app.route('/DieselPowered')
def DieselPowered():
    products = products_df[products_df['Department'] == 'Diesel Washer'].to_dict(orient='records')
    return render_template('dieselWashers.html', products=products)


@app.route('/ElectricPowered')
def ElectricPowered():
    products = products_df[products_df['Department'] == 'Electric Washer'].to_dict(orient='records')
    return render_template('electricWashers.html', products=products)


@app.route('/PTOPowered')
def PTOPowered():
    products = products_df[products_df['Department'] == 'PTO Washer'].to_dict(orient='records')
    return render_template('ptoWashers.html', products=products)


@app.route('/Generators')
def Generators():
    products = products_df[products_df['Department'] == 'Generator'].to_dict(orient='records')
    return render_template('generators.html', products=products)


@app.route('/Parts')
def Parts():
    products = products_df[products_df['Department'] == 'Parts'].to_dict(orient='records')
    return render_template('parts.html', products=products)


@app.route('/MyCart')
def MyCart():
    cart = session.get('cart', [])
    subtotal = sum(item['Price'] * item['Quantity'] for item in cart)
    return render_template('myCart.html', cart=cart, subtotal=subtotal)


@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    data = request.get_json()
    item_id = data.get('id')  # Get the item ID from the request

    if 'cart' in session:
        # Filter the cart to remove the item with the given ID
        session['cart'] = [item for item in session['cart'] if item['ID'] != item_id]
        session.modified = True  # Mark the session as modified
        return jsonify({"success": True, "message": "Item removed from cart"})
    return jsonify({"success": False, "message": "Cart not found"}), 404


@app.route("/", methods=['GET'])
def hello_world():
    response = make_response(render_template('index.html'))
    return response


if __name__ == "__main__":
    app.run(debug=False)


