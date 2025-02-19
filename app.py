from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from pymongo import MongoClient,DESCENDING
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
from datetime import datetime


app = Flask(__name__)

app.config["SECRET_KEY"] = "RMDDashboard"  

# MongoDB connection
client = MongoClient("mongodb://localhost:27017/")
db = client["rmd_database"]
projects_collection = db["projects"]
users_collection = db["users"]
inv_collection = db['inventory']
emp_collection=db['employee']
attendance_col=db["attendance"]
dpr_collection=db["dpr"]
diesel_collection=db["diesel"]

#dashboard.html api calls
@app.route("/get-filter-options", methods=["GET"])
def get_filter_options():
    project_ids = projects_collection.distinct("projectID")
    project_budgets = projects_collection.distinct("projectBudget")
    locations = projects_collection.distinct("location")
    expenditures = projects_collection.distinct("expenditure")
    incomes = projects_collection.distinct("income")

    return jsonify({
        "projectIds": sorted(project_ids),
        "projectBudgets": sorted(project_budgets),
        "locations": locations,
        "expenditures": sorted(expenditures),
        "incomes": sorted(incomes)
    })

@app.route("/filter-projects", methods=["POST"])
def filter_projects():
    filters = request.json
    query = {}

    if filters.get("projectId"):
        query["projectID"] = int(filters["projectId"])
    if filters.get("projectBudget"):
        query["projectBudget"] = int(filters["projectBudget"])
    if filters.get("location"):
        query["location"] = filters["location"]
    if filters.get("expenditure"):
        query["expenditure"] = int(filters["expenditure"])
    if filters.get("income"):
        query["income"] = int(filters["income"])
    # Query the database
    projects = list(projects_collection.find(query, {"_id": 0}))
    return jsonify(projects)
@app.route('/get-chart-data', methods=['POST'])
def get_chart_data():
    filters = request.json
    query = {}

    # Apply filters with validation
    if filters.get("projectId"):
        query["projectID"] = int(filters["projectId"])
    if filters.get("projectBudget"):
        query["projectBudget"] = int(filters["projectBudget"])
    if filters.get("location"):
        query["location"] = filters["location"]
    if filters.get("expenditure"):
        query["expenditure"] = int(filters["expenditure"])
    if filters.get("income"):
        query["income"] = int(filters["income"])

    try:
        # Retrieve filtered projects
        projects = list(projects_collection.find(query, {"_id": 0}))
        # Calculate totals for expenditure and income
        total_expenditure = sum(project.get('expenditure', 0) or 0 for project in projects)
        total_income = sum(project.get('income', 0) or 0 for project in projects)
        total_budget=sum(project.get("projectBudget",0) or 0 for project in projects)
        # Include projects in the response
        return jsonify({
            'totalBudget':total_budget,
            'totalExpenditure': total_expenditure,
            'totalIncome': total_income,
            'projectCount': len(projects)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Add Employee Route (AJAX Request)
@app.route("/add_employee", methods=["POST"])
def add_employee():
    try:
        name = request.form.get("name")
        position = request.form.get("position")
        payout = request.form.get("payout")

        # Validate Input
        if not name or not position or not payout:
            return jsonify({"error": "All fields are required"}), 400

        payout = float(payout)  # Convert payout to float

        emp_collection.insert_one({
            "name": name,
            "position": position,
            "payout": payout,
            "credited": 0,
            "debited": 0
        })
        
        return jsonify({"success": True, "message": "Employee added successfully"}), 200

    except ValueError:
        return jsonify({"error": "Invalid payout value"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Attendance Page
@app.route("/attendance")
def attendance():
    employees = emp_collection.find()
    return render_template("attendance.html", employees=employees)

@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    employee_id = request.form["employee_id"]
    date = datetime.now().strftime("%Y-%m-%d")

    # Check if attendance already marked
    if not attendance_col.find_one({"employee_id": employee_id, "date": date}):
        attendance_col.insert_one({
            "employee_id": employee_id,
            "date": date
        })
    
    return redirect(url_for("attendance"))


# Calculate Salary
@app.route("/calculate_salary")
def calculate_salary():
    employees = emp_collection.find()
    salary_data = []

    for emp in employees:
        total_days = attendance_col.count_documents({"employee_id": str(emp["_id"])})
        salary = total_days * emp["payout"]

        salary_data.append({
            "name": emp["name"],
            "position": emp["position"],
            "total_days": total_days,
            "salary": salary
        })

    return render_template("salary.html", salary_data=salary_data)

# Insert Inventory
@app.route('/insert-inventory', methods=['POST'])
def insert_inventory():
    try:
        data = request.json
        itemID = data.get("itemID")
        itemName = data.get("itemName")
        price=data.get("price")
        quantity = data.get("quantity")
        total_price=price*quantity
        remarks=data.get("remarks")

        if not itemID or not itemName or not isinstance(quantity, int) or quantity <= 0:
            return jsonify({"error": "Invalid input data"}), 400
        if (inv_collection.find_one({"itemID":int(itemID)})):
            return jsonify({"message":"itemID is already existed."})
        
        new_item = {"itemID": int(itemID), "itemName": itemName, "price":price, "quantity": quantity, "total_Price":total_price, "remarks":remarks}
        result = inv_collection.insert_one(new_item)

        return jsonify({"message": "Inventory added successfully", "id": str(result.inserted_id)}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

#for DPR reports 
@app.route('/get_inventory', methods=['GET'])
def get_inventory():
    try:
        items = list(diesel_collection.find({}, {"_id": 0}))
        total_weight = 0
        total_distance = 0
        total_diesel = 0
        
        for item in items:
            item["diesel_left"] = int(item.get("diesel_issued", 0)) - int(item.get("diesel_used", 0))
            total_diesel += int(item.get("diesel_used", 0))
            total_distance += max(0, int(item.get("after_load", 0)) - int(item.get("odo_meter", 0)))
            
            # Fetch load_weight from dpr_collection
            dpr_entry = dpr_collection.find_one({"vehicle_number": item["vehicle_number"]}, {"load_weight": 1, "_id": 0})
            load_weight = int(dpr_entry["load_weight"]) if dpr_entry and "load_weight" in dpr_entry else 1  
            total_weight += load_weight
            
            item["tons_per_1Ldiesel"] = round(load_weight / max(1, int(item.get("diesel_used", 1))), 2) 
        
        return jsonify({
            "items": items,
            "total_weight": total_weight,
            "total_distance": total_distance,
            "total_diesel": total_diesel
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/update_item', methods=['POST'])
def update_item():
    try:
        data = request.json
        sno = data.get("S_No") # Fetch S.No. from request
        updates = data.get("updates")
        if not sno or not updates:
            return jsonify({"error": "Invalid request"}), 400
        if type(updates["S_No"]) == str:
            updates["S_No"]=int(updates["S_No"])
        filter={"S_No":sno}
        result = diesel_collection.update_one(filter, {"$set": updates})
        if result.modified_count > 0:
            return jsonify({"message": "Item updated successfully"}), 200
        else:
            return jsonify({"error": "No changes made or item not found"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/delete_item', methods=['DELETE'])
def delete_item():
    try:
        data = request.json
        sno = data.get("S_No")
        if not sno:
            return jsonify({"error": "Invalid request"}), 400

        result = diesel_collection.delete_one({"S_No": int(sno)})
        if result.deleted_count > 0:
            return jsonify({"message": "Item deleted successfully"}), 200
        else:
            return jsonify({"error": "Item not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

#for item inventory
# Get Inventory
@app.route('/get_inventory_report', methods=['GET'])
def get_inventory_report():
    try:
        items = list(inv_collection.find({}, {"_id": 0, "itemID": 1, "itemName": 1, "quantity": 1, "total_Price":1, "remarks":1}))
        return jsonify(items), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_inv_item', methods=['POST'])
def update_inv_item():
    try:
        data = request.json
        item_id = data.get("itemID")  # Fetch itemID from request
        updates = data.get("updates")  # Get updates dictionary

        if not item_id or not updates:
            return jsonify({"error": "Invalid request"}), 400

        # Convert itemID to integer if needed
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)

        # Ensure itemID inside updates is also an integer
        if "itemID" in updates and isinstance(updates["itemID"], str) and updates["itemID"].isdigit():
            updates["itemID"] = int(updates["itemID"])


        result = inv_collection.update_one({"itemID": item_id}, {"$set": updates})

        if result.modified_count > 0:
            return jsonify({"message": "Item updated successfully"}), 200
        else:
            return jsonify({"error": "No changes made or item not found"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/delete_inv_item', methods=['DELETE'])
def delete_inv_item():
    try:
        data = request.json
        item_id = data.get("itemID")

        if not item_id:
            return jsonify({"error": "Invalid request"}), 400

        # Convert itemID to integer if needed
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)

        result = inv_collection.delete_one({"itemID": item_id})

        if result.deleted_count > 0:
            return jsonify({"message": "Item deleted successfully"}), 200
        else:
            return jsonify({"error": "Item not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

#Routings for templates 
@app.route("/")
def home():
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("home"))
    return render_template("dashboard.html")

@app.route("/dpr_report")
def dpr_report():
    return render_template("dpr_report.html")

@app.route("/inventory")
def inventory():
    return render_template("inventory.html")
@app.route("/upload")
def upload():
    return render_template("upload.html")

@app.route("/employee")
def employe():
    employees=emp_collection.find()
    return render_template("employee.html",employees=employees)

#Login and Signup api's
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    user = users_collection.find_one({"username": username})
    if user and check_password_hash(user["password"], password):
        session["logged_in"] = True
        session["username"] = username
        session["role"] = user.get("role", "user")  # Save the user's role in the session
        return jsonify({"message": "Login successful", "role": user["role"]}), 200
    else:
        return jsonify({"error": "Invalid username or password"}), 401

@app.route("/dpr")
def dpr():
    return render_template("dpr.html")
@app.route("/logout")
def logout():
    session.clear()
    return render_template("login.html")

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    # Check if username already exists
    if users_collection.find_one({"username": username}):
        return jsonify({"error": "Username already exists"}), 409

    # Hash password and save to database
    hashed_password = generate_password_hash(password)
    users_collection.insert_one({
        "username": username,
        "password": hashed_password,
        "role": role
    })

    return jsonify({"message": "Signup successful"}), 201

#dpr api calls
@app.route('/add_vehicle', methods=['POST'])
def add_vehicle():
    try:
        data = request.json
        time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Retrieve the last S_No
        last_entry = dpr_collection.find_one({}, sort=[("S_No", DESCENDING)])
        sno = last_entry["S_No"] + 1 if last_entry else 1  # Increment or start from 1
        # Insert vehicle data
        vehicle_data = {
            "S_No":sno,
            "vehicle_number": data["vehicle_number"],
            "odo_meter": data["odo_meter"],
            "tare_weight": data["tare_weight"],
            "load_weight": data["load_weight"],
            "diesel_issued": data["diesel_issued"]
        }
        dpr_collection.insert_one(vehicle_data)

        # Retrieve the last S_No
        last_entry = diesel_collection.find_one({}, sort=[("S_No", DESCENDING)])
        sno = last_entry["S_No"] + 1 if last_entry else 1  # Increment or start from 1

        # Insert diesel data
        diesel_data = {
            "S_No": sno,
            "vehicle_number": data["vehicle_number"],
            "diesel_issued": data["diesel_issued"],
            "diesel_used": 0,
            "odo_meter": data["odo_meter"],
            "after_load":0,
            "Date": time
        }
        diesel_collection.insert_one(diesel_data)

        return jsonify({"message": "Vehicle added successfully", "S_No": sno}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_dpr', methods=['GET'])
def get_dpr():
    dpr = list(dpr_collection.find({}, {"_id": 0}))
    return jsonify(dpr)

@app.route('/update_vehicle', methods=['POST'])
def update_vehicle():
    data = request.json
    vehicle_number = data.pop("vehicle_number")
    dpr_collection.update_one({"vehicle_number": vehicle_number}, {"$set": data})
    return jsonify({"message": "Vehicle updated successfully"})

@app.route('/delete_vehicle', methods=['DELETE'])
def delete_vhc_item():
    try:
        data = request.json
        sno = data.get("S_No")
        if not sno:
            return jsonify({"error": "Invalid request"}), 400
        sno = int(sno)  # Ensure it's an integer
        result = dpr_collection.delete_one({"S_No": sno})
        if result.deleted_count > 0:
            return jsonify({"message": "Item deleted successfully"}), 200
        else:
            return jsonify({"error": "Item not found"}), 404
    except ValueError:
        return jsonify({"error": "Invalid S_No format. Must be an integer."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/insertProject", methods=['POST'])
def insert_project():
    data = request.json
    project_id = int(data.get("projectId"))
    project_budget = int(data.get("projectBudget"))
    location = data.get("location")
    expenditure = int(data.get("expenditure"))
    income = int(data.get("income"))
    # Check if the project already exists
    if projects_collection.find_one({"projectID": project_id}):
        return jsonify({"error": "Project already exists"}), 409

    # Insert the new project
    projects_collection.insert_one({
        "projectID": project_id,
        "projectBudget": project_budget,
        "location": location,
        "expenditure": expenditure,
        "income": income
    })

    return jsonify({"message": "Project details inserted successfully"}), 201


if __name__ == "__main__":
    app.run(debug=True)
