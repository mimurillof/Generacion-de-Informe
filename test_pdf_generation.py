#!/usr/bin/env python3
"""
Script de prueba para el generador de PDF
Prueba la generación de PDF desde un JSON existente en Supabase
"""

import os
import sys
import json
import requests
from pathlib import Path

# Agregar el directorio actual al path para importar módulos locales
sys.path.insert(0, str(Path(__file__).parent))

def test_pdf_generation_local():
    """
    Prueba 1: Generación de PDF localmente usando el módulo directamente
    """
    print("=" * 80)
    print("PRUEBA 1: Generación de PDF Local (Módulo Directo)")
    print("=" * 80)
    
    try:
        from pdf_generator import execute_generation
        
        # Usuario de prueba
        user_id = "048adfcc-fe6e-4608-9b74-fc5608eed985"
        
        print(f"\n✅ Usuario de prueba: {user_id}")
        print(f"✅ Descargará JSON desde: {user_id}/estructura_informe.json")
        print(f"✅ Subirá PDF a: {user_id}/Reporte.pdf")
        
        # Ejecutar generación
        print("\n🚀 Iniciando generación de PDF...\n")
        
        pdf_path, upload_info = execute_generation(
            json_path_param=None,  # Descargará desde Supabase
            schema_path_param=None,
            output_path_param=None,
            allow_download=True,
            upload_to_supabase=True,
            user_id=user_id  # ✅ MULTIUSUARIO
        )
        
        print("\n" + "=" * 80)
        print("✅ PDF GENERADO EXITOSAMENTE")
        print("=" * 80)
        print(f"📄 Ruta local: {pdf_path}")
        print(f"📤 Info de subida: {json.dumps(upload_info, indent=2)}")
        
        return True
        
    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ ERROR EN GENERACIÓN LOCAL")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pdf_generation_http():
    """
    Prueba 2: Generación de PDF via HTTP (como lo haría el backend)
    """
    print("\n\n" + "=" * 80)
    print("PRUEBA 2: Generación de PDF via HTTP")
    print("=" * 80)
    
    # Detectar URL del servicio
    pdf_service_url = os.getenv("PDF_GENERATOR_URL", "http://localhost:5001")
    
    # Si estamos en Heroku, usar la URL de producción
    if os.getenv("DYNO"):
        pdf_service_url = "https://horizon-pdf-generator-cce9f2017fd6.herokuapp.com"
    
    endpoint = f"{pdf_service_url}/run"
    
    print(f"\n✅ URL del servicio: {endpoint}")
    
    # Usuario de prueba
    user_id = "048adfcc-fe6e-4608-9b74-fc5608eed985"
    
    payload = {
        "user_id": user_id,  # ✅ MULTIUSUARIO
        "json_data": {},  # Vacío, descargará desde Supabase
        "download_from_supabase": True,
        "upload_to_supabase": True
    }
    
    print(f"✅ Usuario: {user_id}")
    print(f"✅ Payload: {json.dumps(payload, indent=2)}")
    
    try:
        print("\n🚀 Enviando petición HTTP...\n")
        
        response = requests.post(
            endpoint,
            json=payload,
            timeout=120  # 2 minutos de timeout
        )
        
        print("\n" + "=" * 80)
        print(f"📊 Status Code: {response.status_code}")
        print("=" * 80)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ PDF GENERADO EXITOSAMENTE VIA HTTP")
            print(f"\n{json.dumps(result, indent=2)}")
            return True
        else:
            print(f"❌ ERROR: Status {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("\n❌ ERROR: Timeout después de 120 segundos")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_heroku_deployment():
    """
    Prueba 3: Verificar que el servicio en Heroku está funcionando
    """
    print("\n\n" + "=" * 80)
    print("PRUEBA 3: Health Check - Servicio en Heroku")
    print("=" * 80)
    
    heroku_url = "https://horizon-pdf-generator-cce9f2017fd6.herokuapp.com"
    
    try:
        print(f"\n✅ URL: {heroku_url}")
        print("🔍 Verificando que el servicio responde...")
        
        # Hacer un GET simple para verificar que el servicio está vivo
        response = requests.get(f"{heroku_url}/", timeout=10)
        
        print(f"\n📊 Status Code: {response.status_code}")
        print(f"📄 Response: {response.text[:200]}...")
        
        if response.status_code in [200, 404]:  # 404 es OK, significa que está vivo
            print("\n✅ Servicio está ONLINE")
            return True
        else:
            print(f"\n⚠️ Servicio respondió con status {response.status_code}")
            return False
            
    except Exception as e:
        print(f"\n❌ ERROR conectando al servicio: {e}")
        return False


if __name__ == "__main__":
    print("\n")
    print("█" * 80)
    print("█" + " " * 78 + "█")
    print("█" + " " * 20 + "TEST SUITE - PDF GENERATOR" + " " * 32 + "█")
    print("█" + " " * 78 + "█")
    print("█" * 80)
    
    # Verificar variables de entorno
    print("\n📋 Variables de Entorno:")
    print(f"  SUPABASE_URL: {'✅ SET' if os.getenv('SUPABASE_URL') else '❌ MISSING'}")
    print(f"  SUPABASE_KEY: {'✅ SET' if os.getenv('SUPABASE_KEY') else '❌ MISSING'}")
    print(f"  PDF_GENERATOR_URL: {os.getenv('PDF_GENERATOR_URL', 'Not set (usará default)')}")
    
    results = {}
    
    # Ejecutar pruebas
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()
        if test_type == "local":
            results["local"] = test_pdf_generation_local()
        elif test_type == "http":
            results["http"] = test_pdf_generation_http()
        elif test_type == "health":
            results["health"] = test_heroku_deployment()
        else:
            print(f"\n❌ Tipo de prueba desconocido: {test_type}")
            print("Uso: python test_pdf_generation.py [local|http|health]")
            sys.exit(1)
    else:
        # Ejecutar todas las pruebas
        results["health"] = test_heroku_deployment()
        results["local"] = test_pdf_generation_local()
        results["http"] = test_pdf_generation_http()
    
    # Resumen final
    print("\n\n" + "█" * 80)
    print("█" + " " * 78 + "█")
    print("█" + " " * 30 + "RESUMEN FINAL" + " " * 35 + "█")
    print("█" + " " * 78 + "█")
    print("█" * 80)
    
    for test_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"  {test_name.upper()}: {status}")
    
    total = len(results)
    passed = sum(1 for s in results.values() if s)
    
    print(f"\n  Total: {passed}/{total} pruebas exitosas")
    
    if passed == total:
        print("\n🎉 TODAS LAS PRUEBAS PASARON")
        sys.exit(0)
    else:
        print(f"\n⚠️ {total - passed} prueba(s) fallaron")
        sys.exit(1)
